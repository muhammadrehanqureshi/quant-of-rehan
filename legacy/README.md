# legacy/ — quarantined code from the deleted repos (reference only)

Provenance (2026-10-05): when the owner ordered `the-sentinel`,
`sentinel-eod` and `psx-kmiall-signal-system` destroyed (GitHub + local),
everything non-trivial was extracted here first. `psx-kmiall-signal-system`
contained only an empty README — nothing to migrate from it.

## What lives here

- `sentinel/` — the sentinel's full `src/` + `tests/` (decision engine,
  intraday snapshot collector, corporate-actions normalizer, psx_core
  universe/session/feed modules, notifier, watchdog).
- `eod/` — sentinel-eod's full `src/` + `tests/` (EOD bot, lock memory,
  corporate actions, morning fade, psx_core mirror, broker feed).

## Rules of engagement

1. **Reference only.** Nothing in `legacy/` is imported by `src/` or run in
   CI. It is quarantined so the signal engine can mine proven logic without
   dragging the old bots' semantics along.
2. **Copies were secret-scanned** before migration (gho_/cfut_/Telegram/
   AWS/private-key patterns): clean. All secrets live in the owner's
   credential sheet and GitHub/Cloudflare secret stores, never in code.
3. **Data is NOT here.** Genuine datasets from those repos (eod corpus,
   corporate-actions tables, intraday snapshots, sweep panels, foreign-flow
   history) were preserved under gitignored `data/legacy_sentinel/`.
   Datasets never enter git (SO-5), code does.
4. Deletion targets were verified empty-of-value before destruction:
   - `psx-kmiall-signal-system` — empty README only → nothing to take.
   - `the-sentinel`, `sentinel-eod` — code + data extracted as above.

## Most valuable pieces for the QUANT's next steps

| Piece | Why it matters |
|---|---|
| `*/src/psx_core/broker_feed.py` | Working read-only broker-feed client (Path A reference) |
| `*/src/corporate_actions.py` + `data/legacy_sentinel/data/corporate_actions*.json` | Proper corporate-action adjustments — kills the 10x recon artifact at the data layer |
| `eod/src/psx_core/universe.py`, `sessions.py`, `feed.py` | Battle-tested PSX universe/session primitives |
| `eod/src/telegram_notify.py` | Signal notification (signal-only, SO-1 compatible) |
| `sentinel/src/build_intraday_dataset.py`, `collect_kmiall_snapshots.py` | Intraday dataset builders for future intrabar work |
