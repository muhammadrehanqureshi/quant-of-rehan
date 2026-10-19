#!/usr/bin/env python3
"""Print the repository name a git remote URL points at.

The landing flow publishes to exactly one repository, and ``.repo-identity``
declares which one. This helper turns whatever ``git remote get-url origin``
prints into the bare repository name so the two can be compared:

    https://github.com/owner/quant-of-rehan.git   -> quant-of-rehan
    git@github.com:owner/quant-of-rehan.git       -> quant-of-rehan
    C:\\Users\\owner\\Desktop\\quant-of-rehan.git  -> quant-of-rehan
    /tmp/sandbox/remote.git                       -> remote

Separators are both handled because a local remote on Windows is printed with
backslashes, and guessing wrong there would either refuse every legitimate
landing or accept the wrong repository.

Run it as a command:

    python scripts/repo_identity.py "$(git remote get-url origin)"
"""

from __future__ import annotations

import re
import sys

_SPLIT = re.compile(r"[/\\]")
_SUFFIX = re.compile(r"\.git$", re.IGNORECASE)


def repository_name(url: str) -> str:
    """Return the bare repository name at the end of ``url``.

    Trailing slashes are ignored, a ``.git`` suffix is dropped, and the last
    path segment is returned whether the segments are separated by slashes or
    backslashes. An empty url has no name, which is the caller's problem to
    refuse.
    """
    cleaned = url.strip().rstrip("/").rstrip("\\")
    if not cleaned:
        return ""
    return _SUFFIX.sub("", _SPLIT.split(cleaned)[-1])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python scripts/repo_identity.py <remote-url>",
              file=sys.stderr)
        return 2
    print(repository_name(args[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
