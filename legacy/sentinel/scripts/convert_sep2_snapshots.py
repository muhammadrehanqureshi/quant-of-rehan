"""One-off (fixed): convert data/snapshots/2026-09-02_raw.bak/ (raw
pretty-printed JSON files) into compact single-line JSONL at
data/snapshots/2026-09-02.jsonl.gz. Replaces the broken concatenation.
"""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "snapshots" / "2026-09-02_raw.bak"
OUT = ROOT / "data" / "snapshots" / "2026-09-02.jsonl.gz"


def main() -> int:
    if not SRC.is_dir():
        print(f"{SRC} not found - nothing to do")
        return 1
    files = sorted(SRC.glob("*.json"))
    print(f"parsing {len(files)} raw snapshots ...")
    n = 0
    skipped = 0
    with gzip.open(OUT, "wt", encoding="utf-8") as out:
        for f in files:
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(obj, dict) or not (obj.get("quotes")):
                    skipped += 1
                    continue
                out.write(json.dumps(obj, separators=(",", ":")) + "\n")
                n += 1
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                skipped += 1
                print(f"  skip {f.name}: {exc}")
    print(f"wrote {n} snapshots ({skipped} skipped) -> {OUT.name}")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
