/**
 * The picker. It offers whatever the service says it can serve and nothing
 * more, so the UI cannot ask for a symbol the backend would refuse.
 */

import type { Resolution } from "../api/types";

export interface SymbolPickerProps {
  readonly symbol: string;
  readonly onSymbol: (symbol: string) => void;
  readonly catalogue: readonly string[];
  readonly resolution: Resolution;
  readonly onResolution: (resolution: Resolution) => void;
  readonly resolutions: readonly Resolution[];
}

export function SymbolPicker(props: SymbolPickerProps) {
  const { symbol, onSymbol, catalogue, resolution, onResolution, resolutions } =
    props;

  return (
    <div className="picker">
      <label className="picker__field">
        <span>Symbol</span>
        <input
          list="symbols"
          value={symbol}
          spellCheck={false}
          autoComplete="off"
          onChange={(event) => onSymbol(event.target.value.toUpperCase().trim())}
          placeholder="OGDC"
        />
        <datalist id="symbols">
          {catalogue.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      </label>

      <label className="picker__field">
        <span>Resolution</span>
        <select
          value={resolution}
          onChange={(event) => onResolution(event.target.value as Resolution)}
        >
          {resolutions.map((item) => (
            <option key={item} value={item}>
              {item === "1m" ? "one minute" : item === "1d" ? "daily" : "session"}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
