/**
 * The wire contract, mirrored on the client and validated at the boundary.
 *
 * The rule here is the same one the Python side follows: a payload is parsed,
 * never cast. A `fetch` response is `unknown` until this module has checked
 * every field a chart draws from, because a chart that renders `undefined`
 * as a price is worse than one that shows an error.
 *
 * The validation is deliberately hand written rather than schema library
 * generated: it is about a hundred lines, it has no dependency, and it
 * produces error messages that name the field and the reason, which is what
 * a human debugging a broken deployment actually needs.
 */

export type Resolution = "1m" | "1d" | "session";

export interface SourceInfo {
  readonly id: string;
  readonly label: string;
  readonly delay_seconds: number;
  readonly note: string;
}

export interface MarketBand {
  readonly open: string;
  readonly close: string;
}

export interface MarketNextEvent {
  readonly event: string;
  readonly at: string;
}

export interface MarketContext {
  readonly phase: string;
  readonly state: string;
  readonly trading_day: boolean;
  readonly timezone: string;
  readonly band: MarketBand | null;
  readonly next_event: MarketNextEvent | null;
  readonly as_of: string;
}

export interface Bar {
  readonly t: string;
  readonly o: number;
  readonly h: number;
  readonly l: number;
  readonly c: number;
  readonly v: number;
}

export interface Gap {
  readonly start: string;
  readonly end: string;
  readonly minutes: number;
  readonly reason: string;
}

export interface IngestError {
  readonly category: string;
  readonly detail: string;
  readonly at: string;
}

export interface IngestHealth {
  readonly polls: number;
  readonly last_poll_at: string;
  readonly watched: readonly string[];
  readonly subscribers: number;
  readonly dropped_events: number;
  readonly errors: Readonly<Record<string, IngestError>>;
  readonly interval_seconds: number;
  readonly resolution: string;
  readonly source: SourceInfo;
}

export interface ChartPayload {
  readonly ok: true;
  readonly schema_version: number;
  readonly as_of: string;
  readonly symbol: string;
  readonly resolution: Resolution;
  readonly source: SourceInfo;
  readonly market: MarketContext;
  readonly bars: readonly Bar[];
  readonly bar_count: number;
  readonly gaps: readonly Gap[];
  readonly notes: readonly string[];
  readonly ingest: IngestHealth;
}

export interface BarEvent {
  readonly event: "bars";
  readonly symbol: string;
  readonly resolution: Resolution;
  readonly as_of: string;
  readonly bars: readonly Bar[];
}

/** Every failure this client can name, mirroring the server's taxonomy. */
export type ErrorCategory =
  | "NETWORK"
  | "CONTRACT"
  | "TIMEOUT"
  | "CONNECTION"
  | "RATE_LIMITED"
  | "HTTP_ERROR"
  | "SCHEMA_CHANGE"
  | "EMPTY_ACK"
  | "CIRCUIT_OPEN"
  | "MISSING_SYMBOL"
  | "UNKNOWN_SYMBOL"
  | "BAD_LIMIT"
  | "UNSUPPORTED_RESOLUTION"
  | "NO_ROUTE"
  | "NO_UI"
  | "INTERNAL";

/** An ISO 8601 stamp carrying its own offset, which is all we accept (SO-8). */
const ISO_WITH_OFFSET =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)$/;

export class ContractViolation extends Error {
  readonly path: string;

  constructor(path: string, reason: string) {
    super(`${path}: ${reason}`);
    this.name = "ContractViolation";
    this.path = path;
  }
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ContractViolation(path, "expected an object");
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new ContractViolation(path, "expected an array");
  }
  return value;
}

function str(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new ContractViolation(path, "expected a string");
  }
  return value;
}

function num(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ContractViolation(path, "expected a finite number");
  }
  return value;
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new ContractViolation(path, "expected a boolean");
  }
  return value;
}

function stamp(value: unknown, path: string): string {
  const text = str(value, path);
  if (!ISO_WITH_OFFSET.test(text)) {
    throw new ContractViolation(
      path,
      "expected ISO 8601 with a UTC offset, the one clock rule (SO-8)",
    );
  }
  return text;
}

function resolution(value: unknown, path: string): Resolution {
  const text = str(value, path);
  if (text !== "1m" && text !== "1d" && text !== "session") {
    throw new ContractViolation(path, `unknown resolution ${text}`);
  }
  return text;
}

function parseSource(raw: unknown, path: string): SourceInfo {
  const value = record(raw, path);
  return {
    id: str(value["id"], `${path}.id`),
    label: str(value["label"], `${path}.label`),
    delay_seconds: num(value["delay_seconds"], `${path}.delay_seconds`),
    note: str(value["note"], `${path}.note`),
  };
}

function parseBar(raw: unknown, path: string): Bar {
  const value = record(raw, path);
  const bar: Bar = {
    t: stamp(value["t"], `${path}.t`),
    o: num(value["o"], `${path}.o`),
    h: num(value["h"], `${path}.h`),
    l: num(value["l"], `${path}.l`),
    c: num(value["c"], `${path}.c`),
    v: num(value["v"], `${path}.v`),
  };
  if (bar.h < Math.max(bar.o, bar.c, bar.l)) {
    throw new ContractViolation(path, "high is below another price");
  }
  if (bar.l > Math.min(bar.o, bar.c, bar.h)) {
    throw new ContractViolation(path, "low is above another price");
  }
  if (bar.v < 0) {
    throw new ContractViolation(path, "volume is negative");
  }
  return bar;
}

export function parseBars(raw: unknown, path = "bars"): Bar[] {
  return array(raw, path).map((item, index) =>
    parseBar(item, `${path}[${index}]`),
  );
}

function parseMarket(raw: unknown, path: string): MarketContext {
  const value = record(raw, path);
  const bandRaw = value["band"];
  const nextRaw = value["next_event"];
  let band: MarketBand | null = null;
  if (bandRaw !== null && bandRaw !== undefined) {
    const inner = record(bandRaw, `${path}.band`);
    band = {
      open: str(inner["open"], `${path}.band.open`),
      close: str(inner["close"], `${path}.band.close`),
    };
  }
  let next: MarketNextEvent | null = null;
  if (nextRaw !== null && nextRaw !== undefined) {
    const inner = record(nextRaw, `${path}.next_event`);
    next = {
      event: str(inner["event"], `${path}.next_event.event`),
      at: stamp(inner["at"], `${path}.next_event.at`),
    };
  }
  return {
    phase: str(value["phase"], `${path}.phase`),
    state: str(value["state"], `${path}.state`),
    trading_day: bool(value["trading_day"], `${path}.trading_day`),
    timezone: str(value["timezone"], `${path}.timezone`),
    band,
    next_event: next,
    as_of: stamp(value["as_of"], `${path}.as_of`),
  };
}

function parseGaps(raw: unknown, path: string): Gap[] {
  return array(raw, path).map((item, index) => {
    const where = `${path}[${index}]`;
    const value = record(item, where);
    return {
      start: stamp(value["start"], `${where}.start`),
      end: stamp(value["end"], `${where}.end`),
      minutes: num(value["minutes"], `${where}.minutes`),
      reason: str(value["reason"], `${where}.reason`),
    };
  });
}

function parseIngest(raw: unknown, path: string): IngestHealth {
  const value = record(raw, path);
  const errorsRaw = record(value["errors"], `${path}.errors`);
  const errors: Record<string, IngestError> = {};
  for (const [symbol, detail] of Object.entries(errorsRaw)) {
    const entry = record(detail, `${path}.errors.${symbol}`);
    errors[symbol] = {
      category: str(entry["category"], `${path}.errors.${symbol}.category`),
      detail: str(entry["detail"], `${path}.errors.${symbol}.detail`),
      at: stamp(entry["at"], `${path}.errors.${symbol}.at`),
    };
  }
  return {
    polls: num(value["polls"], `${path}.polls`),
    last_poll_at: str(value["last_poll_at"], `${path}.last_poll_at`),
    watched: array(value["watched"], `${path}.watched`).map((item, index) =>
      str(item, `${path}.watched[${index}]`),
    ),
    subscribers: num(value["subscribers"], `${path}.subscribers`),
    dropped_events: num(value["dropped_events"], `${path}.dropped_events`),
    errors,
    interval_seconds: num(value["interval_seconds"], `${path}.interval_seconds`),
    resolution: str(value["resolution"], `${path}.resolution`),
    source: parseSource(value["source"], `${path}.source`),
  };
}

export function parsePayload(raw: unknown): ChartPayload {
  const value = record(raw, "payload");
  if (!bool(value["ok"], "payload.ok")) {
    throw new ContractViolation("payload.ok", "the server reported a failure");
  }
  const payload: ChartPayload = {
    ok: true,
    schema_version: num(value["schema_version"], "payload.schema_version"),
    as_of: stamp(value["as_of"], "payload.as_of"),
    symbol: str(value["symbol"], "payload.symbol"),
    resolution: resolution(value["resolution"], "payload.resolution"),
    source: parseSource(value["source"], "payload.source"),
    market: parseMarket(value["market"], "payload.market"),
    bars: parseBars(value["bars"], "payload.bars"),
    bar_count: num(value["bar_count"], "payload.bar_count"),
    gaps: parseGaps(value["gaps"], "payload.gaps"),
    notes: array(value["notes"], "payload.notes").map((item, index) =>
      str(item, `payload.notes[${index}]`),
    ),
    ingest: parseIngest(value["ingest"], "payload.ingest"),
  };
  if (payload.bar_count !== payload.bars.length) {
    throw new ContractViolation(
      "payload.bar_count",
      `says ${payload.bar_count} but carries ${payload.bars.length}`,
    );
  }
  return payload;
}

/** The bars event an open SSE stream sends for each poll. */
export function parseBarEvent(raw: unknown): BarEvent {
  const value = record(raw, "event");
  const name = str(value["event"], "event.event");
  if (name !== "bars") {
    throw new ContractViolation("event.event", `unexpected event ${name}`);
  }
  return {
    event: "bars",
    symbol: str(value["symbol"], "event.symbol"),
    resolution: resolution(value["resolution"], "event.resolution"),
    as_of: stamp(value["as_of"], "event.as_of"),
    bars: parseBars(value["bars"], "event.bars"),
  };
}

/** The health answer's parts that the UI actually shows. */
export interface HealthReport {
  readonly service: string;
  readonly schema_version: number;
  readonly karachi_now: string;
  readonly market: MarketContext;
  readonly source: SourceInfo;
  readonly resolutions: readonly Resolution[];
}

export function parseHealth(raw: unknown): HealthReport {
  const value = record(raw, "health");
  return {
    service: str(value["service"], "health.service"),
    schema_version: num(value["schema_version"], "health.schema_version"),
    karachi_now: stamp(value["karachi_now"], "health.karachi_now"),
    market: parseMarket(value["market"], "health.market"),
    source: parseSource(value["source"], "health.source"),
    resolutions: array(value["resolutions"], "health.resolutions").map(
      (item, index) => resolution(item, `health.resolutions[${index}]`),
    ),
  };
}

/** The catalogue answer: one list of symbols the service can serve. */
export function parseSymbols(raw: unknown): string[] {
  const value = record(raw, "symbols");
  return array(value["symbols"], "symbols.symbols").map((item, index) => {
    const row = record(item, `symbols.symbols[${index}]`);
    return str(row["symbol"], `symbols.symbols[${index}].symbol`);
  });
}

/** The error body the service returns for every non-2xx API answer. */
export function parseErrorBody(raw: unknown): {
  code: ErrorCategory;
  detail: string;
} {
  const value = record(raw, "error");
  const inner = record(value["error"], "error.error");
  return {
    code: str(inner["code"], "error.error.code") as ErrorCategory,
    detail: str(inner["detail"], "error.error.detail"),
  };
}
