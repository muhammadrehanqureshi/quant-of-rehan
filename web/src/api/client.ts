/**
 * The REST + SSE client for the chart service.
 *
 * Three behaviours are worth reading the code for:
 *
 * 1. **Every failure has a category.** A network error, an HTTP status, a
 *    rate limit and a contract violation are different facts about the
 *    world, and the UI says which one happened. Nothing is swallowed.
 * 2. **Retries are bounded and only for retryable answers.** A 503 or a
 *    dropped connection is retried with proportional backoff and jitter, and
 *    the server's own `Retry-After` wins when it sends one. A 400 or a 404
 *    is returned at once: a wrong request does not become right by asking
 *    again.
 * 3. **The stream reconnects by itself.** `EventSource` reconnects after a
 *    dropped connection with its own schedule; this client adds a bounded
 *    backoff on top so a service that is restarting is not hit every second,
 *    and it reports the state it is in rather than pretending to be live.
 *
 * Time and randomness are injectable so the tests can prove all of it
 * without waiting a single real second.
 */

import {
  type BarEvent,
  type ChartPayload,
  type ErrorCategory,
  type Resolution,
  ContractViolation,
  parseBarEvent,
  parseErrorBody,
  parsePayload,
  parseSymbols,
} from "./types";

export class ApiError extends Error {
  readonly category: ErrorCategory;
  readonly status: number;
  readonly retryAfterSeconds: number | null;
  readonly detail: string;

  constructor(
    category: ErrorCategory,
    detail: string,
    options: { status?: number; retryAfterSeconds?: number | null } = {},
  ) {
    super(`${category}: ${detail}`);
    this.name = "ApiError";
    this.category = category;
    this.detail = detail;
    this.status = options.status ?? 0;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }

  /** Is a second attempt plausibly useful? */
  get retryable(): boolean {
    if (this.category === "NETWORK" || this.category === "TIMEOUT") {
      return true;
    }
    if (this.category === "RATE_LIMITED") {
      return true;
    }
    return this.status >= 500;
  }
}

/** The slice of EventSource this client uses, so a test can stand in. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
  onerror: ((event: Event) => void) | null;
  onopen: ((event: Event) => void) | null;
}

export interface ClientOptions {
  /** Base URL of the service; empty means same origin, which is the norm. */
  readonly baseUrl?: string;
  readonly timeoutMs?: number;
  readonly attempts?: number;
  readonly baseDelayMs?: number;
  readonly maxDelayMs?: number;
  readonly fetchImpl?: typeof fetch;
  readonly eventSourceFactory?: (url: string) => EventSourceLike;
  readonly sleep?: (milliseconds: number) => Promise<void>;
  readonly random?: () => number;
}

export interface StreamHandlers {
  onSnapshot: (payload: ChartPayload) => void;
  onBars: (event: BarEvent) => void;
  onState: (state: StreamState, detail?: string) => void;
}

export type StreamState = "connecting" | "live" | "reconnecting" | "closed";

export interface StreamHandle {
  close(): void;
}

const DEFAULTS = {
  timeoutMs: 8000,
  attempts: 3,
  baseDelayMs: 500,
  maxDelayMs: 5000,
} as const;

function defaultEventSource(url: string): EventSourceLike {
  return new EventSource(url);
}

const sleepFor = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

function retryAfterSeconds(headers: Headers): number | null {
  const raw = headers.get("retry-after");
  if (raw === null) {
    return null;
  }
  const seconds = Number.parseFloat(raw);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export class ChartClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly attempts: number;
  private readonly baseDelayMs: number;
  private readonly maxDelayMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly eventSourceFactory: (url: string) => EventSourceLike;
  private readonly sleep: (milliseconds: number) => Promise<void>;
  private readonly random: () => number;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? "";
    this.timeoutMs = options.timeoutMs ?? DEFAULTS.timeoutMs;
    this.attempts = options.attempts ?? DEFAULTS.attempts;
    this.baseDelayMs = options.baseDelayMs ?? DEFAULTS.baseDelayMs;
    this.maxDelayMs = options.maxDelayMs ?? DEFAULTS.maxDelayMs;
    this.fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
    this.eventSourceFactory =
      options.eventSourceFactory ?? defaultEventSource;
    this.sleep = options.sleep ?? sleepFor;
    this.random = options.random ?? Math.random;
  }

  async bars(
    symbol: string,
    resolution: Resolution,
    options: { limit?: number; signal?: AbortSignal } = {},
  ): Promise<ChartPayload> {
    const query = new URLSearchParams({ symbol, resolution });
    if (options.limit !== undefined) {
      query.set("limit", String(options.limit));
    }
    const url = `${this.baseUrl}/api/bars?${query.toString()}`;
    const raw = await this.request(url, options.signal);
    try {
      return parsePayload(raw);
    } catch (error) {
      if (error instanceof ContractViolation) {
        throw new ApiError("CONTRACT", error.message);
      }
      throw error;
    }
  }

  async health(): Promise<unknown> {
    return this.request(`${this.baseUrl}/api/health`);
  }

  /** The symbols this service can serve, for the picker. */
  async symbols(signal?: AbortSignal): Promise<string[]> {
    const raw = await this.request(`${this.baseUrl}/api/symbols`, signal);
    try {
      return parseSymbols(raw);
    } catch (error) {
      if (error instanceof ContractViolation) {
        throw new ApiError("CONTRACT", error.message);
      }
      throw error;
    }
  }

  /**
   * Open the live stream for one symbol.
   *
   * The returned handle closes everything, including a pending reconnect:
   * a component that unmounts must not leave a timer behind.
   */
  stream(
    symbol: string,
    resolution: Resolution,
    handlers: StreamHandlers,
  ): StreamHandle {
    const query = new URLSearchParams({ symbol, resolution });
    const path = `/api/stream?${query.toString()}`;
    const url = this.baseUrl.length > 0 ? `${this.baseUrl}${path}` : path;
    let closed = false;
    let source: EventSourceLike | null = null;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const open = () => {
      if (closed) {
        return;
      }
      handlers.onState(attempt === 0 ? "connecting" : "reconnecting");
      source = this.eventSourceFactory(url);
      source.onopen = () => {
        attempt = 0;
        handlers.onState("live");
      };
      source.addEventListener("snapshot", (event: MessageEvent) => {
        try {
          handlers.onSnapshot(parsePayload(JSON.parse(String(event.data))));
        } catch (error) {
          handlers.onState("reconnecting", describe(error));
        }
      });
      source.addEventListener("bars", (event: MessageEvent) => {
        try {
          handlers.onBars(parseBarEvent(JSON.parse(String(event.data))));
        } catch (error) {
          handlers.onState("reconnecting", describe(error));
        }
      });
      source.addEventListener("idle", () => {
        // The service says nothing has happened for a while. That is not an
        // error; the stream itself is still open.
        handlers.onState("live");
      });
      source.onerror = () => {
        if (closed) {
          return;
        }
        source?.close();
        source = null;
        attempt += 1;
        const ceiling = this.maxDelayMs + this.baseDelayMs * attempt;
        const delay = Math.min(
          ceiling,
          this.baseDelayMs * 2 ** (attempt - 1) * (0.5 + this.random()),
        );
        handlers.onState(
          "reconnecting",
          `stream interrupted, reconnecting in ${Math.round(delay / 100) / 10}s`,
        );
        timer = setTimeout(open, delay);
      };
    };

    open();

    return {
      close: () => {
        closed = true;
        if (timer !== null) {
          clearTimeout(timer);
          timer = null;
        }
        source?.close();
        source = null;
        handlers.onState("closed");
      },
    };
  }

  /** One request with a timeout, a bounded retry loop and named failures. */
  private async request(url: string, signal?: AbortSignal): Promise<unknown> {
    let lastError: ApiError | null = null;
    for (let attempt = 1; attempt <= this.attempts; attempt += 1) {
      try {
        return await this.once(url, signal);
      } catch (error) {
        const failure =
          error instanceof ApiError
            ? error
            : new ApiError("INTERNAL", describe(error));
        lastError = failure;
        if (!failure.retryable || attempt === this.attempts) {
          throw failure;
        }
        const fromServer = failure.retryAfterSeconds;
        const backoff = Math.min(
          this.maxDelayMs,
          this.baseDelayMs * 2 ** (attempt - 1) * (0.5 + this.random()),
        );
        const waitMs =
          fromServer !== null
            ? Math.min(this.maxDelayMs, fromServer * 1000)
            : backoff;
        await this.sleep(waitMs);
      }
    }
    throw lastError ?? new ApiError("INTERNAL", "no attempt was made");
  }

  private async once(url: string, signal?: AbortSignal): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    if (signal !== undefined) {
      signal.addEventListener("abort", () => controller.abort(), {
        once: true,
      });
    }
    let response: Response;
    try {
      response = await this.fetchImpl(url, { signal: controller.signal });
    } catch (error) {
      if (controller.signal.aborted) {
        throw new ApiError("TIMEOUT", `no answer within ${this.timeoutMs}ms`);
      }
      throw new ApiError("NETWORK", describe(error));
    } finally {
      clearTimeout(timeout);
    }
    const body = await this.readJson(response);
    if (!response.ok) {
      const parsed = safeErrorBody(body);
      throw new ApiError(parsed.code, parsed.detail, {
        status: response.status,
        retryAfterSeconds: retryAfterSeconds(response.headers),
      });
    }
    if (body === null) {
      throw new ApiError("CONTRACT", "the answer was not JSON");
    }
    return body;
  }

  private async readJson(response: Response): Promise<unknown> {
    try {
      const text = await response.text();
      return text.length === 0 ? null : JSON.parse(text);
    } catch {
      return null;
    }
  }
}

function safeErrorBody(raw: unknown): { code: ErrorCategory; detail: string } {
  try {
    return parseErrorBody(raw);
  } catch {
    return { code: "INTERNAL", detail: "the service sent no usable error body" };
  }
}

function describe(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
