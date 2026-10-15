# QoR secret hygiene

**Law (SO-5): no credentials, no personal data, no trading data under version
control. Ever. Not in the tip, not in history.**

Incident 2026-10-15 proved the point: the repo became public for a window and the
legacy recon material went internet-readable. It came back private because of
these rules; keep them standing.

## What may never be committed

- API keys, tokens, account IDs, passwords, PINs, session files (`.env`,
  `*_token.txt`, `secrets*/`)
- broker login material of any kind: cookies, session journals with credentials,
  portal captures, password pools
- personal data: CNIC, passport, phone numbers, home or office addresses,
  bank/IBAN numbers, portfolio statements, balances, trade history exports
- URLs carrying a user and password pair inside the address

Secrets live in these places only, and nowhere else:

1. GitHub Actions secrets (never echoed to logs)
2. Cloudflare worker secrets (`npx wrangler secret put NAME`)
3. A local, **un-synced** `.env` that `.gitignore` already excludes
4. The owner's password manager

## How the repo enforces it

- `.github/workflows/secret-scan.yml` runs gitleaks (pinned by commit SHA,
  `--redact` so echoed values never reach the CI log) on every push and PR,
  over the FULL commit history (`fetch-depth: 0`).
- `scripts/hooks/pre-commit` re-runs the scan locally on staged files.

## Enabling the pre-commit hook (one command, per clone)

```bash
git config core.hooksPath scripts/hooks
```

The hook fails closed: if it cannot run the scan, it refuses the commit and says
so. It never prints a matched value; it prints kind, file and line only.

## Reporting

If you see a credential in this repository, do not open a public issue about it.
Contact the owner directly.
