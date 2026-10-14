/**
 * The client's failure handling, proven with fake transports and a fake
 * clock: no test waits a real second or opens a real connection.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type EventSourceLike,
  ChartClient,
  type StreamState,
} from "./client";

function payloadBody() {
  return {
    ok: true,
    schema_version: 1,
    as_of: "2026-10-12T11:00:00+05:00",
    symbol: "OGDC",
    resolution: "1m",
    source: { id: "broker_tape", label: "tape", delay_seconds: 0, note: "" },
    market: {
      phase: "OPEN",
      state: "MARKET",
      trading_day: true,
      timezone: "Asia/Karachi",
      band: null,
      next_event: null,
      as_of: "2026-10-12T11:00:00+05:00",
    },
    bars: [],
    bar_count: 0,
    gaps: [],
    notes: [],
    ingest: {
      polls: 1,
      last_poll_at: "",
      watched: [],
      subscribers: 1,
      dropped_events: 0,
      errors: {},
      interval_seconds: 15,
      resolution: "1m",
      source: { id: "broker_tape", label: "tape", delay_seconds: 0, note: "" },
    },
  };
}

function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function errorResponse(
  status: number,
  code: string,
  detail: string,
  headers: Record<string, string> = {},
) {
  return jsonResponse(status, { ok: false, error: { code, detail } }, headers);
}

function clientWith(
  fetchImpl: typeof fetch,
  options: { attempts?: number; timeoutMs?: number } = {},
): { client: ChartClient; sleeps: number[] } {
  const sleeps: number[] = [];
  const client = new ChartClient({
    fetchImpl,
    attempts: options.attempts ?? 3,
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    baseDelayMs: 100,
    maxDelayMs: 1000,
    sleep: (milliseconds) => {
      sleeps.push(milliseconds);
      return Promise.resolve();
    },
    random: () => 0,
  });
  return { client, sleeps };
}

class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  private readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();
  onerror: ((event: Event) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(data) } as MessageEvent);
    }
  }

  fireError(): void {
    this.onerror?.({} as Event);
  }

  fireOpen(): void {
    this.onopen?.({} as Event);
  }
}

afterEach(() => {
  FakeEventSource.instances = [];
  vi.useRealTimers();
});

describe("bars", () => {
  it("returns a validated payload", async () => {
    const calls: string[] = [];
    const { client } = clientWith((input) => {
      calls.push(String(input));
      return Promise.resolve(jsonResponse(200, payloadBody()));
    });
    const payload = await client.bars("OGDC", "1m");
    expect(payload.symbol).toBe("OGDC");
    expect(calls[0]).toContain("/api/bars?symbol=OGDC&resolution=1m");
  });

  it("retries a 503 and then succeeds", async () => {
    let attempt = 0;
    const { client, sleeps } = clientWith(() => {
      attempt += 1;
      return Promise.resolve(
        attempt === 1
          ? errorResponse(503, "RATE_LIMITED", "slow down")
          : jsonResponse(200, payloadBody()),
      );
    });
    const payload = await client.bars("OGDC", "1m");
    expect(payload.ok).toBe(true);
    expect(attempt).toBe(2);
    expect(sleeps.length).toBe(1);
  });

  it("honours the server's Retry-After header, capped by the ceiling", async () => {
    let attempt = 0;
    const { client, sleeps } = clientWith(() => {
      attempt += 1;
      return Promise.resolve(
        attempt === 1
          ? errorResponse(503, "RATE_LIMITED", "slow down", {
              "retry-after": "2",
            })
          : jsonResponse(200, payloadBody()),
      );
    });
    await client.bars("OGDC", "1m");
    // The server asked for two seconds; this client's own ceiling is one.
    expect(sleeps[0]).toBe(1000);
  });

  it("does not retry a 400", async () => {
    let attempt = 0;
    const { client, sleeps } = clientWith(() => {
      attempt += 1;
      return Promise.resolve(errorResponse(400, "BAD_LIMIT", "limit"));
    });
    await expect(client.bars("OGDC", "1m")).rejects.toBeInstanceOf(ApiError);
    expect(attempt).toBe(1);
    expect(sleeps).toEqual([]);
  });

  it("names the category and the status of an HTTP failure", async () => {
    const { client } = clientWith(() =>
      Promise.resolve(errorResponse(404, "UNKNOWN_SYMBOL", "not in universe")),
    );
    await expect(client.bars("NOPE", "1m")).rejects.toMatchObject({
      category: "UNKNOWN_SYMBOL",
      status: 404,
      detail: "not in universe",
    });
  });

  it("times out and says so", async () => {
    const { client } = clientWith(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
      { attempts: 1, timeoutMs: 10 },
    );
    await expect(client.bars("OGDC", "1m")).rejects.toMatchObject({
      category: "TIMEOUT",
    });
  });

  it("classifies a transport error as a network failure and retries it", async () => {
    let attempt = 0;
    const { client } = clientWith(() => {
      attempt += 1;
      return attempt < 2
        ? Promise.reject(new TypeError("fetch failed"))
        : Promise.resolve(jsonResponse(200, payloadBody()));
    });
    const payload = await client.bars("OGDC", "1m");
    expect(payload.ok).toBe(true);
    expect(attempt).toBe(2);
  });

  it("refuses a payload that violates the contract", async () => {
    const broken = { ...payloadBody(), bar_count: 9 };
    const { client } = clientWith(() =>
      Promise.resolve(jsonResponse(200, broken)),
    );
    await expect(client.bars("OGDC", "1m")).rejects.toMatchObject({
      category: "CONTRACT",
    });
  });

  it("handles a non JSON error body without crashing", async () => {
    const { client } = clientWith(
      () =>
        Promise.resolve(
          new Response("<html>gateway</html>", {
            status: 502,
            headers: { "content-type": "text/html" },
          }),
        ),
    );
    await expect(client.bars("OGDC", "1m")).rejects.toMatchObject({
      category: "INTERNAL",
      status: 502,
    });
  });
});

describe("stream", () => {
  const factory = (url: string) => new FakeEventSource(url);

  it("delivers a snapshot then bars, and reports its state", () => {
    const states: StreamState[] = [];
    const snapshots: string[] = [];
    const bars: number[] = [];
    const client = new ChartClient({ eventSourceFactory: factory });
    const handle = client.stream("OGDC", "1m", {
      onSnapshot: (payload) => snapshots.push(payload.symbol),
      onBars: (event) => bars.push(event.bars.length),
      onState: (state) => states.push(state),
    });
    const source = FakeEventSource.instances[0];
    expect(source).toBeDefined();
    expect(source?.url).toContain("/api/stream?symbol=OGDC&resolution=1m");

    source?.fireOpen();
    source?.emit("snapshot", payloadBody());
    source?.emit("bars", {
      event: "bars",
      symbol: "OGDC",
      resolution: "1m",
      as_of: "2026-10-12T11:01:00+05:00",
      bars: [],
    });

    expect(states).toContain("connecting");
    expect(states).toContain("live");
    expect(snapshots).toEqual(["OGDC"]);
    expect(bars).toEqual([0]);
    handle.close();
  });

  it("reconnects with a bounded backoff when the stream drops", () => {
    vi.useFakeTimers();
    const client = new ChartClient({ eventSourceFactory: factory, random: () => 0 });
    const states: StreamState[] = [];
    const handle = client.stream("OGDC", "1m", {
      onSnapshot: () => undefined,
      onBars: () => undefined,
      onState: (state) => states.push(state),
    });
    expect(FakeEventSource.instances.length).toBe(1);
    FakeEventSource.instances[0]?.fireError();
    expect(states).toContain("reconnecting");
    expect(FakeEventSource.instances.length).toBe(1);

    vi.advanceTimersByTime(1000);
    expect(FakeEventSource.instances.length).toBe(2);
    handle.close();
    vi.advanceTimersByTime(10_000);
    expect(FakeEventSource.instances.length).toBe(2);
  });

  it("does not reconnect after close", () => {
    vi.useFakeTimers();
    const client = new ChartClient({ eventSourceFactory: factory });
    const handle = client.stream("OGDC", "1m", {
      onSnapshot: () => undefined,
      onBars: () => undefined,
      onState: () => undefined,
    });
    handle.close();
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances.length).toBe(1);
  });

  it("reports a contract violation on the stream instead of throwing", () => {
    const failures: string[] = [];
    const client = new ChartClient({ eventSourceFactory: factory });
    const handle = client.stream("OGDC", "1m", {
      onSnapshot: () => undefined,
      onBars: () => undefined,
      onState: (_state, detail) => {
        if (detail !== undefined) {
          failures.push(detail);
        }
      },
    });
    FakeEventSource.instances[0]?.emit("bars", {
      event: "bars",
      symbol: "OGDC",
      resolution: "1m",
      as_of: "2026-10-12T11:01:00+05:00",
      bars: [{}],
    });
    expect(failures.length).toBe(1);
    expect(failures[0]).toMatch(/bars\[0\]/);
    handle.close();
  });
});
