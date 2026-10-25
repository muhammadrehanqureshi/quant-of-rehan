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

/**
 * Every rung of the timeframe ladder the service serves.
 *
 * The server is the authority: a rung appears in this type because it is in
 * the payload contract, not because the browser invented a button for it.
 * `1d` and `session` stay in the union so a pre-v3 deployment still parses.
 */
export type Resolution =
  | "1s" | "10s" | "1m" | "5m" | "10m" | "15m" | "30m" | "1h" | "4h"
  | "1D" | "1W" | "1M"
  | "1d" | "session";

/** The canonical order the UI offers, finest first. */
export const RESOLUTIONS: readonly Resolution[] = [
  "1s", "10s", "1m", "5m", "10m", "15m", "30m", "1h", "4h",
  "1D", "1W", "1M",
];

const RESOLUTION_SET = new Set<string>(RESOLUTIONS);
const RESOLUTION_ALIASES: Readonly<Record<string, Resolution>> = {
  "1d": "1D",
  "1w": "1W",
  "1hour": "1h",
  "1hr": "1h",
  "60m": "1h",
  "240m": "4h",
  session: "1D",
};

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

/**
 * Which session a series belongs to, and where those bars came from (v2).
 *
 * This is what makes the chart usable at any hour: a finished session says so
 * in words, names the recording it was read from, and carries the hash that
 * proves it, so a reader can never mistake Friday's candles for a live market.
 */
export interface ChartSession {
  readonly day: string;
  readonly current: boolean;
  readonly archived: boolean;
  readonly source: string;
  readonly capture: CaptureIdentity | null;
  readonly built_at: string;
  readonly note: string;
  readonly volume_available: boolean;
}

export interface CaptureIdentity {
  readonly name: string;
  readonly bytes: number;
  readonly mtime_ns: number;
  readonly sha256: string;
}

export interface ChartPayload {
  readonly ok: true;
  readonly schema_version: number;
  readonly as_of: string;
  readonly symbol: string;
  readonly resolution: Resolution;
  readonly source: SourceInfo;
  readonly market: MarketContext;
  readonly session: ChartSession;
  readonly bars: readonly Bar[];
  readonly bar_count: number;
  readonly gaps: readonly Gap[];
  readonly notes: readonly string[];
  readonly ingest: IngestHealth;
}

/** One row of the symbol catalogue, with per-session facts when asked. */
export interface SymbolRow {
  readonly symbol: string;
  readonly source: string;
  readonly listed: boolean;
  /** True for the computed KSE100 and KMIALLSHR proxies. */
  readonly index: boolean | undefined;
  readonly bars: number | null;
  readonly first: string | null;
  readonly last: string | null;
  readonly close: number | null;
  /** The session's own open and measured range, for change and range columns.
   * Absent facts stay null; an older service answers without them. */
  readonly open?: number | null;
  readonly high?: number | null;
  readonly low?: number | null;
  /** The session's summed volume across the printed minutes. */
  readonly volume?: number | null;
  readonly day: string | null;
}

/** One session the service can draw: live on disk, or stored durably. */
export interface SessionRow {
  readonly day: string;
  readonly current: boolean;
  readonly archived: boolean;
  readonly capture: CaptureIdentity | null;
  readonly archive: ArchiveSummary | null;
  readonly sources: readonly string[];
}

export interface ArchiveSummary {
  readonly day: string;
  readonly symbols: number;
  readonly bars: number;
  readonly priced_bars: number;
  readonly carried_bars: number;
  readonly volume_available: boolean;
  readonly capture: CaptureIdentity | null;
  readonly built_at: string;
  readonly builds: number;
  readonly first_observation: string | null;
  readonly notes: readonly string[];
}

export interface SessionsReport {
  readonly today: string;
  readonly timezone: string;
  readonly sessions: readonly SessionRow[];
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
  | "BAD_DAY"
  | "UNSUPPORTED_DAY"
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
  if (RESOLUTION_SET.has(text)) {
    return text as Resolution;
  }
  const alias = RESOLUTION_ALIASES[text];
  if (alias !== undefined) {
    return alias;
  }
  throw new ContractViolation(path, `unknown resolution ${text}`);
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

function parseCapture(raw: unknown, path: string): CaptureIdentity | null {
  if (raw === null || raw === undefined) {
    return null;
  }
  const value = record(raw, path);
  return {
    name: str(value["name"], `${path}.name`),
    bytes: num(value["bytes"], `${path}.bytes`),
    mtime_ns: num(value["mtime_ns"], `${path}.mtime_ns`),
    sha256: str(value["sha256"], `${path}.sha256`),
  };
}

/**
 * Read the session block, tolerating an answer from a pre-v2 service.
 *
 * A payload without one is not rejected: the fields degrade to "unknown
 * session", which the status bar renders as such rather than inventing a day.
 */
function parseSessionBlock(raw: unknown, path: string): ChartSession {
  if (raw === null || raw === undefined) {
    return {
      day: "",
      current: true,
      archived: false,
      source: "",
      capture: null,
      built_at: "",
      note: "",
      volume_available: false,
    };
  }
  const value = record(raw, path);
  const capture = parseCapture(value["capture"], `${path}.capture`);
  return {
    day: str(value["day"], `${path}.day`),
    current: bool(value["current"], `${path}.current`),
    archived: bool(value["archived"], `${path}.archived`),
    source: str(value["source"], `${path}.source`),
    capture,
    built_at: str(value["built_at"], `${path}.built_at`),
    note: str(value["note"], `${path}.note`),
    volume_available: bool(value["volume_available"] ?? false,
                           `${path}.volume_available`),
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
    session: parseSessionBlock(value["session"], "payload.session"),
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
  readonly timeframes: readonly TimeframeInfo[] | undefined;
  readonly indices: readonly string[] | undefined;
}

/** The service's own label and build note for one rung. */
export interface TimeframeInfo {
  readonly id: Resolution;
  readonly label: string;
  readonly kind: string;
  readonly seconds: number | null;
  readonly minutes: number | null;
  readonly source: string;
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
    timeframes: parseTimeframes(value["timeframes"], "health.timeframes"),
    indices: value["indices"] === undefined
      ? undefined
      : array(value["indices"], "health.indices").map((item, index) =>
          str(item, `health.indices[${index}]`),
        ),
  };
}

/** The optional timeframe detail list; an older service simply omits it. */
function parseTimeframes(
  raw: unknown,
  path: string,
): readonly TimeframeInfo[] | undefined {
  if (raw === undefined || raw === null) {
    return undefined;
  }
  return array(raw, path).map((item, index) => {
    const where = `${path}[${index}]`;
    const value = record(item, where);
    return {
      id: resolution(value["id"], `${where}.id`),
      label: str(value["label"], `${where}.label`),
      kind: str(value["kind"], `${where}.kind`),
      seconds: value["seconds"] === null
        ? null
        : num(value["seconds"], `${where}.seconds`),
      minutes: value["minutes"] === null
        ? null
        : num(value["minutes"], `${where}.minutes`),
      source: str(value["source"], `${where}.source`),
    };
  });
}

/** The catalogue answer: one list of symbols the service can serve. */
export function parseSymbols(raw: unknown): string[] {
  return parseSymbolRows(raw).map((row) => row.symbol);
}

function optionalStr(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalNum(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The full catalogue, including the per-session facts when the service
 * answers them: how many bars a symbol has, when it first and last printed,
 * and its close. A missing fact stays null rather than becoming a zero, so a
 * watchlist can say "nothing in this session" instead of printing 0.00.
 */
export function parseSymbolRows(raw: unknown): SymbolRow[] {
  const value = record(raw, "symbols");
  return array(value["symbols"], "symbols.symbols").map((item, index) => {
    const row = record(item, `symbols.symbols[${index}]`);
    return {
      symbol: str(row["symbol"], `symbols.symbols[${index}].symbol`),
      source: optionalStr(row["source"]) ?? "",
      listed: row["listed"] === undefined ? true : bool(row["listed"], `symbols.symbols[${index}].listed`),
      index: row["index"] === undefined
        ? undefined
        : bool(row["index"], `symbols.symbols[${index}].index`),
      bars: optionalNum(row["bars"]),
      first: optionalStr(row["first"]),
      last: optionalStr(row["last"]),
      close: optionalNum(row["close"]),
      open: optionalNum(row["open"]),
      high: optionalNum(row["high"]),
      low: optionalNum(row["low"]),
      volume: optionalNum(row["volume"]),
      day: optionalStr(row["day"]),
    };
  });
}

/** The prints answer: one symbol's order ledger, as the tape printed it. */
export function parsePrints(raw: unknown): PrintReport {
  const value = record(raw, "prints");
  const noteList = value["notes"];
  const totalsRaw = value["totals"];
  let totals: PrintTotals | null = null;
  if (totalsRaw !== null && totalsRaw !== undefined) {
    const row = record(totalsRaw, "prints.totals");
    totals = {
      orders: optionalNum(row["orders"]),
      volume: optionalNum(row["volume"]),
      prints: num(row["prints"], "prints.totals.prints"),
      buy_volume: optionalNum(row["buy_volume"]),
      sell_volume: optionalNum(row["sell_volume"]),
      classified_volume: optionalNum(row["classified_volume"]),
      unclassified_volume: optionalNum(row["unclassified_volume"]),
      coverage: optionalNum(row["coverage"]),
    };
  }
  return {
    symbol: str(value["symbol"], "prints.symbol"),
    day: optionalStr(value["day"]) ?? "",
    totals,
    events_total: num(value["events_total"], "prints.events_total"),
    notes: noteList === undefined ? [] : array(noteList, "prints.notes").map(String),
    events: array(value["events"] ?? [], "prints.events").map(
      (item, index) => {
        const row = record(item, `prints.events[${index}]`);
        return {
          t: str(row["t"], `prints.events[${index}].t`),
          price: num(row["price"], `prints.events[${index}].price`),
          size: optionalNum(row["size"]),
          trades: optionalNum(row["trades"]),
          volume: optionalNum(row["volume"]),
          change: optionalStr(row["change"]) ?? "flat",
          side: optionalStr(row["side"]) ?? "",
        };
      }),
  };
}

/** One order print the tape itself carried: a trade as the venue saw it. */
export interface PrintEvent {
  /** Print clock, ISO with the +05:00 offset the tape speaks. */
  readonly t: string;
  readonly price: number;
  /** The venue's own size of this last print, when it reports one. */
  readonly size: number | null;
  /** The venue's cumulative order counter at this moment. */
  readonly trades: number | null;
  /** The venue's cumulative share counter at this moment. */
  readonly volume: number | null;
  /** Against the print before it: "up", "down" or "flat". */
  readonly change: string;
  /**
   * The print's own side, classified from the venue's book: "B" when the
   * print sat at the ask (a buyer lifted), "S" at the bid, and "" when the
   * carry no evidence. The same quote-then-tick law the buy/sell split uses.
   */
  readonly side: string;
}

export interface PrintTotals {
  /** The venue's own highest order counter for the session. */
  readonly orders: number | null;
  /** The venue's own highest share counter for the session. */
  readonly volume: number | null;
  /** How many fresh prints this tape saw for the symbol. */
  readonly prints: number;
  /** Share count the evidence assigned to the buyer. */
  readonly buy_volume: number | null;
  /** Share count the evidence assigned to the seller. */
  readonly sell_volume: number | null;
  /** Buy plus sell, carried for audit; null when no window was classified. */
  readonly classified_volume: number | null;
  /** Shares the tape saw before it had a previous print to carry from. */
  readonly unclassified_volume: number | null;
  /** Classified share of the counter; null when the counter is absent or zero. */
  readonly coverage: number | null;
}

export interface PrintReport {
  readonly symbol: string;
  readonly day: string;
  readonly totals: PrintTotals | null;
  readonly events: readonly PrintEvent[];
  readonly events_total: number;
  readonly notes: readonly string[];
}

/** The sessions answer: what this service can draw right now, and where. */
export function parseSessions(raw: unknown): SessionsReport {
  const value = record(raw, "sessions");
  return {
    today: str(value["today"], "sessions.today"),
    timezone: str(value["timezone"], "sessions.timezone"),
    sessions: array(value["sessions"], "sessions.sessions").map(
      (item, index) => {
        const path = `sessions.sessions[${index}]`;
        const row = record(item, path);
        const archiveRaw = row["archive"];
        let archive: ArchiveSummary | null = null;
        if (archiveRaw !== null && archiveRaw !== undefined) {
          const inner = record(archiveRaw, `${path}.archive`);
          archive = {
            day: str(inner["day"], `${path}.archive.day`),
            symbols: num(inner["symbols"], `${path}.archive.symbols`),
            bars: num(inner["bars"], `${path}.archive.bars`),
            priced_bars: num(inner["priced_bars"], `${path}.archive.priced_bars`),
            carried_bars: num(inner["carried_bars"], `${path}.archive.carried_bars`),
            volume_available: bool(inner["volume_available"],
                                   `${path}.archive.volume_available`),
            capture: parseCapture(inner["capture"], `${path}.archive.capture`),
            built_at: str(inner["built_at"], `${path}.archive.built_at`),
            builds: num(inner["builds"], `${path}.archive.builds`),
            first_observation: optionalStr(inner["first_observation"]),
            notes: array(inner["notes"], `${path}.archive.notes`).map(
              (line, at) => str(line, `${path}.archive.notes[${at}]`),
            ),
          };
        }
        return {
          day: str(row["day"], `${path}.day`),
          current: bool(row["current"], `${path}.current`),
          archived: bool(row["archived"], `${path}.archived`),
          capture: parseCapture(row["capture"], `${path}.capture`),
          archive,
          sources: array(row["sources"] ?? [], `${path}.sources`).map(
            (entry, at) => str(entry, `${path}.sources[${at}]`),
          ),
        };
      },
    ),
  };
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
