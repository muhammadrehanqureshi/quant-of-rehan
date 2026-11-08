# Intraday data quality report

Generated 2026-11-08T12:19:40.387478+05:00 (Asia/Karachi).

A complete session starts at or before the regular open and ends at or after
the last regular close minus one minute. A session that starts late is
partial even when it has a full afternoon tape.

| Day | Weekday | Symbols | 1m bars | Fresh | Carried | Stale | Missing min | Dups | Out of order | First observation | Last observation | Complete |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 2026-10-12 | Monday | 299 | 28,732 | 11,543 | 6,740 | 8,224 | 74,807 | 12007 | 0 | 10:24 | 15:45 | no |
| 2026-10-15 | Thursday | 312 | 611 | 583 | 0 | 28 | 0 | 18 | 0 | 17:45 | 18:31 | no |
| 2026-10-16 | Friday | 312 | 108,252 | 19,679 | 558 | 35,094 | 26,423 | 251207 | 0 | 10:05 | 21:10 | no |
| 2026-10-19 | Monday | 298 | 5,066 | 2,377 | 0 | 2,689 | 0 | 9312 | 0 | 15:13 | 15:29 | no |
| 2026-10-20 | Tuesday | 298 | 66,865 | 21,102 | 0 | 45,465 | 40,117 | 148248 | 0 | 09:52 | 15:30 | no |
| 2026-10-21 | Wednesday | 298 | 103,276 | 28,400 | 0 | 68,916 | 9,368 | 231354 | 0 | 09:52 | 15:49 | no |
| 2026-10-22 | Thursday | 297 | 59,865 | 16,677 | 0 | 37,535 | 51,398 | 129518 | 0 | 12:24 | 15:48 | no |
| 2026-10-23 | Friday | 292 | 74,923 | 19,145 | 0 | 34,220 | 27,102 | 171846 | 0 | 10:31 | 16:29 | no |
| 2026-10-26 | Monday | 297 | 58,977 | 15,798 | 0 | 37,239 | 53,289 | 130864 | 0 | 09:00 | 15:49 | yes |
| 2026-10-27 | Tuesday | 297 | 99,347 | 28,958 | 0 | 64,207 | 13,161 | 248205 | 0 | 09:00 | 15:49 | yes |
| 2026-10-28 | Wednesday | 297 | 99,702 | 29,904 | 0 | 63,559 | 12,505 | 247034 | 0 | 09:00 | 15:49 | yes |
| 2026-10-29 | Thursday | 296 | 102,407 | 32,552 | 0 | 63,905 | 8,795 | 219586 | 0 | 09:52 | 15:49 | no |
| 2026-10-30 | Friday | 300 | 44,067 | 14,898 | 0 | 25,352 | 42,791 | 91100 | 0 | 11:22 | 16:30 | no |
| 2026-11-02 | Monday | 296 | 106,940 | 30,580 | 855 | 69,277 | 5,256 | 263044 | 0 | 09:00 | 15:49 | yes |
| 2026-11-03 | Tuesday | 297 | 95,621 | 28,695 | 0 | 66,357 | 11,274 | 237092 | 0 | 09:00 | 15:30 | yes |
| 2026-11-04 | Wednesday | 296 | 56,393 | 21,074 | 423 | 34,626 | 49,845 | 216975 | 0 | 08:57 | 15:24 | no |
| 2026-11-05 | Thursday | 299 | 108,567 | 38,187 | 0 | 64,101 | 4,754 | 586931 | 0 | 09:37 | 15:50 | no |
| 2026-11-06 | Friday | 299 | 79,823 | 29,144 | 0 | 47,374 | 5,798 | 443216 | 0 | 09:19 | 16:30 | no |

Sessions: 18. Complete: 5.
Missing inside the study window: 2026-10-13, 2026-10-14.
Required for selection: 60 complete sessions.

Per-symbol rows for every session are in `data/research/backtest_forensic_audit.json`
under each session's `symbols` list. The JSON is the evidence; this table is the
session summary.
