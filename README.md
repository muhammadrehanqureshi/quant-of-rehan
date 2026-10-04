# Quant of Rehan

![Quant of Rehan](assets/quant_of_rehan_logo.png)

**Private, signal-only quantitative research platform for PSX KMIALL stocks.**
No order placement. No broker integration for trading. Signals and research only.

## Standing Orders (hardcoded — see [GOVERNANCE.md](GOVERNANCE.md))

1. **Signal-only.** The bot never places, modifies, or cancels any order. Ever.
2. **PR first, merge to `master` myself.** Every change lands via a pull request
   that the agent opens and merges. No direct pushes to `master` after bootstrap.
3. **Never fabricate data.** If footprint / order-flow data does not exist, the
   system prints `FOOTPRINT DATA UNAVAILABLE / DEGRADED` and disables that
   engine. No fake bid/ask, ever.
4. **Backtesting runs locally only.** GitHub Actions minutes are capped
   (2,000/month plan); heavy compute never touches Actions.
5. **Secrets never enter the repo.** Credentials live on the owner's Desktop
   files, Windows Credential Manager, and GitHub Secrets — nothing else.

## Layout

```
assets/                 Branding (Quant of Rehan logo)
src/data/registry.py    Data-source capability registry (footprint honesty layer)
tests/                  Unit tests (run locally: python -m unittest discover -s tests)
scripts/check_governance.py   Secret-leak + governance scanner (run in CI on every PR)
GOVERNANCE.md           Hardcoded standing orders
DATA_SOURCING.md        Market-data research memo: what exists, what does not
```

## Running the checks locally

```bash
python scripts/check_governance.py
python -m unittest discover -s tests
```
