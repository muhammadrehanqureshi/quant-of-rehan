"""PR guard: parse every workflow YAML before it can reach master.

Why (2026-10-02): a push landed workflow YAML with an ungrantable
permission (workflows: write) and GitHub answered with startup_failure
runs - red-X emails to the owner for zero work done. This script is
the tripwire: every pull request re-parses all workflow files here and
fails the PR before merge if any file cannot parse or carries a
permission key GitHub refuses for the workflow's own GITHUB_TOKEN.
Without PyYAML the parse check degrades to a warning - the permission
tripwire still runs (stdlib only).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WF_DIR = Path(".github") / "workflows"

# 'workflows:' is refused for the workflow's own GITHUB_TOKEN at ANY
# level (proved 2026-10-01: dispatch refused, startup_failure emailed).
# An indented "workflows: read|write" under a permissions block is
# always that case in these files.
BAD_PERMISSION = re.compile(r"(?m)^\s+workflows:\s*(read|write|none)\s*$")


def main() -> int:
    if not WF_DIR.is_dir():
        print("pr-guard: no .github/workflows dir - nothing to check")
        return 0
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
        print("pr-guard: PyYAML unavailable - parse check skipped, "
              "permission tripwire still armed")

    failures: list[str] = []
    files = sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yaml"))
    for path in files:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{path}: not utf-8 ({exc})")
            continue
        if yaml is not None:
            try:
                yaml.safe_load(text)
            except Exception as exc:  # noqa: BLE001 - any parse failure counts
                failures.append(f"{path}: YAML parse error: {exc}")
        for match in BAD_PERMISSION.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            failures.append(
                f"{path}:{line_no}: 'workflows' permission is not grantable "
                "- startup_failure guaranteed (2026-10-01 incident)"
            )
    if failures:
        print("pr-guard FAILED:")
        for failure in failures:
            print("  " + failure)
        return 1
    print(f"pr-guard OK: {len(files)} workflow file(s) parse clean, "
          "no ungrantable permissions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
