/**
 * A tiny, safe expression language for custom indicators.
 *
 * No `eval`, no `Function`, no property access, no loops: only numbers, the
 * seven series fields, arithmetic and a fixed set of vector functions. The
 * evaluator returns a Float64Array so every result can become an indicator
 * line, and an invalid formula is a named error rather than a dead canvas.
 *
 * Example formulas:
 *
 *     ema(close, 20) - ema(close, 50)
 *     rsi(close, 14)
 *     (close - sma(close, 20)) / stddev(close, 20)
 *     highest(high, 20) - lowest(low, 20)
 */

import {
  atr,
  elementwise,
  ema,
  filled,
  highest,
  lowest,
  rateOfChange,
  rsi,
  sma,
  standardDeviation,
} from "./math";
import type { SeriesData } from "./types";

export class FormulaError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FormulaError";
  }
}

type Value = number | Float64Array;

interface Token {
  readonly kind: "number" | "ident" | "op" | "lparen" | "rparen" | "comma";
  readonly text: string;
  readonly at: number;
}

type Node =
  | { kind: "number"; value: number }
  | { kind: "ref"; name: string }
  | { kind: "unary"; op: string; operand: Node }
  | { kind: "binary"; op: string; left: Node; right: Node }
  | { kind: "call"; name: string; args: Node[] };

const SERIES = new Set([
  "open", "high", "low", "close", "volume", "hl2", "ohlc4",
]);

const FUNCTIONS = new Set([
  "sma", "ema", "rsi", "atr", "stddev", "highest", "lowest", "roc",
  "change", "abs", "sqrt", "log", "exp", "min", "max", "nz", "obv",
]);

const MAX_SOURCE = 400;
const MAX_TOKENS = 256;
const MAX_DEPTH = 48;

function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  while (index < source.length) {
    const character = source[index] ?? "";
    if (/\s/.test(character)) {
      index += 1;
      continue;
    }
    if (/[0-9.]/.test(character)) {
      const start = index;
      while (index < source.length && /[0-9.]/.test(source[index] ?? "")) {
        index += 1;
      }
      if (/[eE]/.test(source[index] ?? "")) {
        index += 1;
        if (/[+-]/.test(source[index] ?? "")) {
          index += 1;
        }
        while (index < source.length && /[0-9]/.test(source[index] ?? "")) {
          index += 1;
        }
      }
      const text = source.slice(start, index);
      if (!Number.isFinite(Number(text))) {
        throw new FormulaError(`"${text}" is not a number (at ${start})`);
      }
      tokens.push({ kind: "number", text, at: start });
      continue;
    }
    if (/[A-Za-z_]/.test(character)) {
      const start = index;
      while (index < source.length && /[A-Za-z0-9_]/.test(source[index] ?? "")) {
        index += 1;
      }
      tokens.push({ kind: "ident", text: source.slice(start, index), at: start });
      continue;
    }
    if (character === "(") {
      tokens.push({ kind: "lparen", text: character, at: index });
      index += 1;
      continue;
    }
    if (character === ")") {
      tokens.push({ kind: "rparen", text: character, at: index });
      index += 1;
      continue;
    }
    if (character === ",") {
      tokens.push({ kind: "comma", text: character, at: index });
      index += 1;
      continue;
    }
    if ("+-*/%^".includes(character)) {
      tokens.push({ kind: "op", text: character, at: index });
      index += 1;
      continue;
    }
    throw new FormulaError(`unexpected character "${character}" at ${index}`);
  }
  if (tokens.length > MAX_TOKENS) {
    throw new FormulaError("the formula is too long to be safe");
  }
  return tokens;
}

class Parser {
  private index = 0;
  private depth = 0;

  constructor(private readonly tokens: readonly Token[]) {}

  parse(): Node {
    const node = this.additive();
    if (this.index < this.tokens.length) {
      const token = this.tokens[this.index];
      throw new FormulaError(
        `unexpected "${token?.text ?? ""}" at ${token?.at ?? 0}`);
    }
    return node;
  }

  private peek(): Token | undefined {
    return this.tokens[this.index];
  }

  private take(): Token {
    const token = this.tokens[this.index];
    if (token === undefined) {
      throw new FormulaError("the formula ends too early");
    }
    this.index += 1;
    return token;
  }

  private additive(): Node {
    let left = this.multiplicative();
    while (this.peek()?.kind === "op" &&
           ((this.peek()?.text ?? "") === "+" ||
            (this.peek()?.text ?? "") === "-")) {
      const op = this.take().text;
      const right = this.multiplicative();
      left = { kind: "binary", op, left, right };
    }
    return left;
  }

  private multiplicative(): Node {
    let left = this.power();
    while (this.peek()?.kind === "op" &&
           ["*", "/", "%"].includes(this.peek()?.text ?? "")) {
      const op = this.take().text;
      const right = this.power();
      left = { kind: "binary", op, left, right };
    }
    return left;
  }

  private power(): Node {
    const left = this.unary();
    if (this.peek()?.kind === "op" && this.peek()?.text === "^") {
      this.take();
      return { kind: "binary", op: "^", left, right: this.power() };
    }
    return left;
  }

  private unary(): Node {
    if (this.peek()?.kind === "op" &&
        ((this.peek()?.text ?? "") === "-" ||
         (this.peek()?.text ?? "") === "+")) {
      const op = this.take().text;
      return { kind: "unary", op, operand: this.unary() };
    }
    return this.primary();
  }

  private primary(): Node {
    this.depth += 1;
    if (this.depth > MAX_DEPTH) {
      throw new FormulaError("the formula is nested too deeply");
    }
    const token = this.take();
    if (token.kind === "number") {
      this.depth -= 1;
      return { kind: "number", value: Number(token.text) };
    }
    if (token.kind === "ident") {
      const name = token.text.toLowerCase();
      if (this.peek()?.kind === "lparen") {
        if (!FUNCTIONS.has(name)) {
          throw new FormulaError(`unknown function "${token.text}"`);
        }
        this.take();
        const args: Node[] = [];
        if (this.peek()?.kind !== "rparen") {
          args.push(this.additive());
          while (this.peek()?.kind === "comma") {
            this.take();
            args.push(this.additive());
          }
        }
        if (this.take().kind !== "rparen") {
          throw new FormulaError(`"${token.text}" is missing a closing ")"`);
        }
        this.depth -= 1;
        return { kind: "call", name, args };
      }
      if (!SERIES.has(name)) {
        throw new FormulaError(`unknown series "${token.text}"`);
      }
      this.depth -= 1;
      return { kind: "ref", name };
    }
    if (token.kind === "lparen") {
      const node = this.additive();
      if (this.take().kind !== "rparen") {
        throw new FormulaError("missing a closing \")\"");
      }
      this.depth -= 1;
      return node;
    }
    throw new FormulaError(`unexpected "${token.text}" at ${token.at}`);
  }
}

function asArray(value: Value, length: number): Float64Array {
  if (typeof value === "number") {
    return filled(length, value);
  }
  return value;
}

function map(value: Value, length: number, fn: (x: number) => number): Value {
  if (typeof value === "number") {
    return fn(value);
  }
  const out = new Float64Array(length);
  for (let index = 0; index < length; index += 1) {
    out[index] = fn(value[index] ?? Number.NaN);
  }
  return out;
}

function binary(
  left: Value,
  right: Value,
  length: number,
  fn: (a: number, b: number) => number,
): Value {
  if (typeof left === "number" && typeof right === "number") {
    return fn(left, right);
  }
  return elementwise(left, right, length, (a, b) => fn(a, b));
}

function scalar(value: Value, name: string): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  throw new FormulaError(`${name} needs a single number`);
}

function seriesValue(value: Value, _name: string, length: number): Float64Array {
  if (typeof value === "number") {
    return filled(length, value);
  }
  return value;
}

function safe(value: number): number {
  return Number.isFinite(value) ? value : Number.NaN;
}

export function compileFormula(source: string): (data: SeriesData) => Float64Array {
  const clean = source.trim();
  if (clean.length === 0) {
    throw new FormulaError("the formula is empty");
  }
  if (clean.length > MAX_SOURCE) {
    throw new FormulaError(`the formula is longer than ${MAX_SOURCE} characters`);
  }
  const tree = new Parser(tokenize(clean)).parse();

  const evaluate = (node: Node, data: SeriesData): Value => {
    switch (node.kind) {
      case "number":
        return node.value;
      case "ref": {
        switch (node.name) {
          case "open": return data.open;
          case "high": return data.high;
          case "low": return data.low;
          case "close": return data.close;
          case "volume": return data.volume;
          case "hl2": return binary(data.high, data.low, data.length,
            (a, b) => (a + b) / 2);
          case "ohlc4": return binary(
            binary(data.open, data.high, data.length, (a, b) => a + b),
            binary(data.low, data.close, data.length, (a, b) => a + b),
            data.length,
            (a, b) => a / 4 + b / 4,
          );
          default:
            throw new FormulaError(`unknown series "${node.name}"`);
        }
      }
      case "unary": {
        const operand = evaluate(node.operand, data);
        return map(operand, data.length, (x) => node.op === "-" ? -x : x);
      }
      case "binary": {
        const left = evaluate(node.left, data);
        const right = evaluate(node.right, data);
        return binary(left, right, data.length, (a, b) => {
          switch (node.op) {
            case "+": return safe(a + b);
            case "-": return safe(a - b);
            case "*": return safe(a * b);
            case "/": return b === 0 ? Number.NaN : safe(a / b);
            case "%": return b === 0 ? Number.NaN : safe(a % b);
            case "^": return safe(Math.pow(a, b));
            default: throw new FormulaError(`unknown operator "${node.op}"`);
          }
        });
      }
      case "call": {
        const args = node.args.map((arg) => evaluate(arg, data));
        const length = data.length;
        switch (node.name) {
          case "sma":
            return sma(seriesValue(args[0] ?? Number.NaN, "sma", length),
              scalar(args[1] ?? Number.NaN, "sma period"));
          case "ema":
            return ema(seriesValue(args[0] ?? Number.NaN, "ema", length),
              scalar(args[1] ?? Number.NaN, "ema period"));
          case "rsi":
            return rsi(seriesValue(args[0] ?? Number.NaN, "rsi", length),
              args.length > 1 ? scalar(args[1] ?? 14, "rsi period") : 14);
          case "atr":
            if (args.length === 1) {
              return atr(data.high, data.low, data.close,
                scalar(args[0] ?? 14, "atr period"));
            }
            return atr(
              seriesValue(args[0] ?? Number.NaN, "atr high", length),
              seriesValue(args[1] ?? Number.NaN, "atr low", length),
              seriesValue(args[2] ?? Number.NaN, "atr close", length),
              scalar(args[3] ?? 14, "atr period"));
          case "stddev":
            return standardDeviation(
              seriesValue(args[0] ?? Number.NaN, "stddev", length),
              scalar(args[1] ?? 20, "stddev period"));
          case "highest":
            return highest(
              seriesValue(args[0] ?? Number.NaN, "highest", length),
              scalar(args[1] ?? 20, "highest period"));
          case "lowest":
            return lowest(
              seriesValue(args[0] ?? Number.NaN, "lowest", length),
              scalar(args[1] ?? 20, "lowest period"));
          case "roc":
            return rateOfChange(
              seriesValue(args[0] ?? Number.NaN, "roc", length),
              scalar(args[1] ?? 10, "roc period"));
          case "change": {
            const values = seriesValue(args[0] ?? Number.NaN, "change", length);
            const period = args.length > 1
              ? Math.max(1, Math.floor(scalar(args[1] ?? 1, "change period")))
              : 1;
            const out = filled(length);
            for (let index = period; index < length; index += 1) {
              out[index] = (values[index] ?? 0) - (values[index - period] ?? 0);
            }
            return out;
          }
          case "abs": return map(args[0] ?? Number.NaN, length, Math.abs);
          case "sqrt": return map(args[0] ?? Number.NaN, length,
            (x) => x < 0 ? Number.NaN : Math.sqrt(x));
          case "log": return map(args[0] ?? Number.NaN, length,
            (x) => x <= 0 ? Number.NaN : Math.log(x));
          case "exp": return map(args[0] ?? Number.NaN, length, Math.exp);
          case "min": return binary(args[0] ?? Number.NaN, args[1] ?? Number.NaN,
            length, Math.min);
          case "max": return binary(args[0] ?? Number.NaN, args[1] ?? Number.NaN,
            length, Math.max);
          case "nz": {
            const fallback = args.length > 1
              ? scalar(args[1] ?? 0, "nz fallback")
              : 0;
            return map(args[0] ?? Number.NaN, length,
              (x) => Number.isNaN(x) ? fallback : x);
          }
          case "obv": {
            const close = seriesValue(args[0] ?? data.close, "obv close", length);
            const volume = seriesValue(args[1] ?? data.volume, "obv volume", length);
            const out = filled(length);
            let running = 0;
            for (let index = 0; index < length; index += 1) {
              if (index > 0) {
                const move = (close[index] ?? 0) - (close[index - 1] ?? 0);
                running += move > 0 ? (volume[index] ?? 0)
                  : move < 0 ? -(volume[index] ?? 0) : 0;
              }
              out[index] = running;
            }
            return out;
          }
          default:
            throw new FormulaError(`unknown function "${node.name}"`);
        }
      }
    }
  };

  return (data: SeriesData): Float64Array => {
    const result = evaluate(tree, data);
    return asArray(result, data.length);
  };
}

/**
 * Compile a formula and run it once against a synthetic, well-formed series.
 *
 * The editor uses this instead of only compiling: syntax can be perfect while
 * a call is still impossible (`sma(close, close)`), and the reader deserves
 * that sentence in the panel rather than a silently missing line. The sample
 * is never drawn and never touches the live bars.
 */
export function validateFormula(source: string): void {
  const run = compileFormula(source);
  const length = 16;
  const time = new Float64Array(length);
  const open = new Float64Array(length);
  const high = new Float64Array(length);
  const low = new Float64Array(length);
  const close = new Float64Array(length);
  const volume = new Float64Array(length);
  for (let index = 0; index < length; index += 1) {
    const price = 100 + index;
    time[index] = index * 60_000;
    open[index] = price;
    high[index] = price + 1;
    low[index] = price - 1;
    close[index] = price + 0.5;
    volume[index] = 1_000 + index;
  }
  run({ length, time, open, high, low, close, volume });
}
