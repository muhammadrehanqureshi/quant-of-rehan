/**
 * The top bar, in TradingView's shape.
 *
 * Left: the brand, the watchlist toggle, the symbol button that opens the
 * quick search, the timeframe chips, the labeled Indicators button and the
 * session picker. Right: reload and the theme. Group separators between the
 * clusters, as on the trading terminal. Everything offered here exists in
 * the service's own answer - the chips are only the resolutions it serves,
 * and the session menu only the days it can draw - so nothing on this bar
 * can silently fail.
 */

import type { Resolution, SessionRow } from "../api/types";
import { formatDay } from "../chart/format";
import { TIMEFRAMES, timeframeLabel } from "../chart/timeframes";

export interface ToolbarProps {
  readonly symbol: string;
  readonly resolution: Resolution;
  readonly onResolution: (resolution: Resolution) => void;
  readonly resolutions: readonly Resolution[];
  /** The chosen session day, or "" for the live one. */
  readonly day: string;
  readonly onDay: (day: string) => void;
  readonly sessions: readonly SessionRow[];
  readonly theme: "dark" | "light";
  readonly onTheme: (theme: "dark" | "light") => void;
  readonly onRefresh: () => void;
  readonly busy: boolean;
  readonly watchlistOpen: boolean;
  readonly onToggleWatchlist: () => void;
  readonly indicatorsOpen: boolean;
  readonly onToggleIndicators: () => void;
  readonly onSearch: () => void;
}

export function Toolbar(props: ToolbarProps) {
  const {
    symbol, resolution, onResolution, resolutions, day, onDay, sessions,
    theme, onTheme, onRefresh, busy, watchlistOpen, onToggleWatchlist,
    indicatorsOpen, onToggleIndicators, onSearch,
  } = props;
  const available = TIMEFRAMES.filter((item) => resolutions.includes(item.id));

  return (
    <header className="toolbar">
      <div className="toolbar__cell">
        <span className="toolbar__brand" title="Charts of Rehan - the PSX chart terminal">
          <span className="toolbar__brand-mark" aria-hidden="true">CR</span>
          <span className="toolbar__brand-name">CHARTS OF REHAN</span>
        </span>

        <button
          type="button"
          className="toolbar__icon"
          aria-expanded={watchlistOpen}
          aria-label={watchlistOpen ? "hide watchlist" : "show watchlist"}
          onClick={onToggleWatchlist}
          title="Show or hide the watchlist"
        >
          ▤
        </button>
      </div>

      <div className="toolbar__sep" aria-hidden="true" />

      <div className="toolbar__cell">
        <button
          type="button"
          className="toolbar__symbol"
          onClick={onSearch}
          title="Choose a symbol (opens the quick search)"
        >
          <span className="toolbar__symbol-name">{symbol || "symbol"}</span>
          <span className="toolbar__symbol-caret" aria-hidden="true">▾</span>
        </button>
      </div>

      <div className="toolbar__sep" aria-hidden="true" />

      <div className="toolbar__cell toolbar__cell--grow" role="group"
           aria-label="timeframe">
        {available.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === resolution
              ? "toolbar__chip toolbar__chip--on"
              : "toolbar__chip"}
            aria-pressed={item.id === resolution}
            title={timeframeLabel(item.id)}
            onClick={() => onResolution(item.id)}
          >
            {item.short}
          </button>
        ))}
      </div>

      <div className="toolbar__cell">
        <button
          type="button"
          className={indicatorsOpen ? "toolbar__menu toolbar__menu--on"
            : "toolbar__menu"}
          aria-expanded={indicatorsOpen}
          aria-label={indicatorsOpen ? "hide indicators" : "show indicators"}
          title="Show or hide the indicators panel"
          onClick={onToggleIndicators}
        >
          Indicators
          <span className="toolbar__symbol-caret" aria-hidden="true">▾</span>
        </button>
      </div>

      <div className="toolbar__sep" aria-hidden="true" />

      <div className="toolbar__cell toolbar__cell--end">
        <label className="toolbar__session">
          <span className="visually-hidden">session</span>
          <select
            aria-label="session"
            value={day}
            onChange={(event) => onDay(event.target.value)}
          >
            <option value="">recent · 5 sessions merged</option>
            {sessions.map((row) => (
              <option key={row.day} value={row.day}>
                {formatDay(`${row.day}T00:00:00+05:00`)}
                {row.current ? " (today)" : ""}
                {row.archived ? " · stored" : ""}
              </option>
            ))}
          </select>
        </label>

        <button type="button" className="toolbar__icon" onClick={onRefresh}
                disabled={busy}
                aria-label="reload the chart from the service"
                title={busy ? "loading…" : "Reload"}>
          ↻
        </button>
        <button
          type="button"
          className="toolbar__icon"
          onClick={() => onTheme(theme === "dark" ? "light" : "dark")}
          aria-label={`switch to the ${theme === "dark" ? "light" : "dark"} theme`}
          title="Light or dark"
        >
          {theme === "dark" ? "☾" : "☀"}
        </button>
      </div>
    </header>
  );
}
