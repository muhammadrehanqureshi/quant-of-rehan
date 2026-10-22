/**
 * The quick symbol search, the way TradingView does it.
 *
 * Open it and the list is already there, ready to click: the session's
 * traded symbols first, the universe after. Typing narrows it as fast as
 * the keys land, the arrows walk it, Enter opens the highlighted row with
 * or without typing, and Escape closes. No second screen, no confirm, no
 * retyping: one surface that answers both "switch" and "add".
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { SymbolRow } from "../api/types";

export interface SymbolSearchProps {
  readonly open: boolean;
  readonly rows: readonly SymbolRow[];
  /** Typography state: the list is loaded, not the picker's problem. */
  readonly loading: boolean;
  readonly onPick: (symbol: string) => void;
  readonly onClose: () => void;
  /** Label the action rows carry in place of "add", when adding is the mode. */
  readonly action?: "switch" | "add";
}

/** Indexes and the symbols that traded lead; the rest follows alphabetically. */
function ordered(rows: readonly SymbolRow[]): readonly SymbolRow[] {
  return [...rows].sort((left, right) => {
    const leftRanked = Number(left.index === true) * 2 + Number((left.bars ?? 0) > 0);
    const rightRanked = Number(right.index === true) * 2 + Number((right.bars ?? 0) > 0);
    if (leftRanked !== rightRanked) {
      return rightRanked - leftRanked;
    }
    return left.symbol.localeCompare(right.symbol);
  });
}

export function SymbolSearch(props: SymbolSearchProps) {
  const { open, rows, loading, onPick, onClose, action = "switch" } = props;
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const list = useMemo(() => ordered(rows), [rows]);

  const matches = useMemo(() => {
    const needle = query.trim().toUpperCase();
    if (needle.length === 0) {
      return list.slice(0, 40);
    }
    return list
      .filter((row) =>
        needle.split(/\s+/).every((part) => row.symbol.includes(part)))
      .slice(0, 40);
  }, [list, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // Focus lands on the frame, so typing starts immediately and the
      // list is fully clickable before any character arrives.
      window.setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  const walk = (delta: number) => {
    setCursor((current) => {
      if (matches.length === 0) {
        return 0;
      }
      const moved = (current + delta) % matches.length;
      return moved < 0 ? moved + matches.length : moved;
    });
  };

  const pick = (index: number) => {
    const row = matches[index];
    if (row !== undefined) {
      onPick(row.symbol);
      onClose();
    }
  };

  const headline = action === "add"
    ? "Add a symbol to the watchlist"
    : "Choose a symbol";

  return (
    <>
      <div className="quicksearch__scrim" onClick={onClose}
           aria-hidden="true" />
      <div className="quicksearch" role="dialog" aria-label={headline}>
        <input
          ref={input}
          type="text"
          className="quicksearch__input"
          role="combobox"
          aria-expanded={matches.length > 0}
          aria-controls="quicksearch-options"
          aria-autocomplete="list"
          value={query}
          spellCheck={false}
          autoComplete="off"
          placeholder="Search the PSX tape…"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              walk(1);
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              walk(-1);
            } else if (event.key === "Enter") {
              event.preventDefault();
              pick(cursor);
            }
          }}
        />
        {loading ? (
          <p className="quicksearch__quiet">reading the catalogue…</p>
        ) : matches.length === 0 ? (
          <p className="quicksearch__quiet">
            {query.trim().length === 0
              ? "the service reported no symbols for this session"
              : `nothing on the tape matches ${query.trim().toUpperCase()}`}
          </p>
        ) : (
          <ul className="quicksearch__list" id="quicksearch-options"
              role="listbox">
            {matches.map((row, index) => {
              const close = row.close;
              return (
                <li key={row.symbol}>
                  <button
                    type="button"
                    role="option"
                    className={"quicksearch__row" +
                      (index === cursor ? " quicksearch__row--cursor" : "")}
                    aria-selected={index === cursor}
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => pick(index)}
                  >
                    <span className="quicksearch__symbol">
                      {row.symbol}
                      {row.index === true
                        ? <span className="row__badge">index</span>
                        : null}
                    </span>
                    <span className="quicksearch__price">
                      {close === null
                        ? <span className="quicksearch__quiet-inline">
                            {(row.bars ?? 0) > 0 ? "no price" : "no bars"}
                          </span>
                        : close.toFixed(2)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <p className="quicksearch__foot">
          ↑ ↓ walk · Enter opens · Esc closes - {matches.length === rows.length
            ? `${rows.length} symbols`
            : `${matches.length} of ${rows.length} symbols`}
        </p>
      </div>
    </>
  );
}
