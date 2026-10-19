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
  type WebSocketLike,
} from "./client";

function payloadBody() {
  return {
    ok: true,
    schema_version: 1,
    as_of: "2026-10-12T11:00:00+05:00",
    observed_at: "2026-10-12T10:59:30+05:00",
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

function liveQuoteBody(symbol = "OGDC", observedAt = "2026-10-12T11:01:00+05:00") {
  return {
    symbol,
    price: 280.25,
    bid: 280,
    ask: 280.5,
    change: 2.25,
    change_pct: 0.81,
    volume: 1200,
    high: 281,
    low: 278,
    status: "OPEN",
    source_tick_time: "11:01:00",
    observed_at: observedAt,
    age_seconds: 2,
    fresh: true,
    source: "eClear MKT-FEED REG",
  };
}

class FakeWebSocket implements WebSocketLike {
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  private readonly listeners = new Map<string, ((event: Event | MessageEvent) => void)[]>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: "open" | "error" | "message", listener: (event: Event | MessageEvent) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: "open" | "error" | "message", data?: unknown): void {
    const event = type === "message"
      ? { data: JSON.stringify(data) } as MessageEvent
      : {} as Event;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
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
  FakeWebSocket.instances = [];
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

describe("live quotes", () => {
  it("selects the requested symbol from the REST snapshot", async () => {
    const calls: string[] = [];
    const { client } = clientWith((input) => {
      calls.push(String(input));
      return Promise.resolve(jsonResponse(200, {
        ok: true,
        stale: false,
        quotes: [liveQuoteBody("HBL"), liveQuoteBody()],
      }));
    });
    const quote = await client.liveQuote("ogdc");
    expect(quote.symbol).toBe("OGDC");
    expect(quote.price).toBe(280.25);
    expect(calls[0]).toContain("/quotes?symbol=OGDC");
  });

  it("uses a fresh symbol update from WebSocket and reconnects cleanly", () => {
    vi.useFakeTimers();
    const states: StreamState[] = [];
    const quotes: number[] = [];
    const client = new ChartClient({
      quoteBaseUrl: "https://relay.example",
      webSocketFactory: (url) => new FakeWebSocket(url),
      baseDelayMs: 100,
      maxDelayMs: 1000,
    });
    const stream = client.streamLiveQuote("OGDC", {
      onQuote: (quote) => quotes.push(quote.price),
      onState: (state) => states.push(state),
    });
    const first = FakeWebSocket.instances[0];
    expect(first?.url).toBe("wss://relay.example/quotes/stream?symbol=OGDC");
    first?.emit("open");
    first?.emit("message", { quotes: [liveQuoteBody()] });
    first?.emit("error");
    expect(first?.closed).toBe(true);
    vi.advanceTimersByTime(100);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(quotes).toEqual([280.25]);
    expect(states).toContain("live");
    expect(states).toContain("reconnecting");
    stream.close();
    expect(FakeWebSocket.instances[1]?.closed).toBe(true);
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
