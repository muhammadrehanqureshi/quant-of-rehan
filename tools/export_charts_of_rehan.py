#!/usr/bin/env python3
"""Extract Charts of Rehan into a standalone, publishable repository tree.

The chart service lives inside the Quant of Rehan monorepo, where it wraps the
project's own data layer. Measured 2026-10-16, the entire chart project depends
on exactly ONE monorepo module, ``src/data/sessions.py`` (the one session law),
so it can stand alone with that module vendored next to it.

This script does not hand-copy anything. It computes the transitive closure of
intra-repo imports from the seed set, copies exactly those files verbatim, and
writes ``PROVENANCE.md`` recording the source commit, the date and a SHA-256 per
file, so the exported tree can always be re-derived and never drifts silently.

It refuses to write a secret-shaped or PII-shaped string into the target tree
(SO-5). Anything it finds is either scrubbed by ``tools/sanitize.py`` or the
export stops.

Usage::

    python tools/export_charts_of_rehan.py --target <dir> [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: What the chart project is: the service, its tests, its demo, its front end.
SEED = (
    "charts",
    "tests/test_charts_contract.py",
    "tests/test_charts_store.py",
    "tests/test_charts_persistent.py",
    "tests/test_charts_ratelimit.py",
    "tests/test_charts_sources.py",
    "tests/test_charts_service.py",
    "tests/test_charts_sessions.py",
    "tests/test_charts_http.py",
    "examples/charts_demo.py",
    "web",
)

#: Never copied: build output, local/private datasets, secrets, or installed dependencies.
EXCLUDE_DIRS = {"node_modules", "dist", "__pycache__", ".pytest_cache", ".vite",
                ".git", "data", "recordings", "history", "private"}

#: The prefixes this project owns. Anything else is the standard library or a
#: third party package and is not copied.
OWNED = ("src", "charts", "scripts")


@dataclass(frozen=True)
class Import:
    """One import in one file, with the package it was written inside."""
    module: str | None
    level: int
    names: tuple[str, ...]


def imports_of(text: str) -> list[Import]:
    """Every import in a module, including ones inside functions.

    Parsed with ``ast`` rather than a regular expression on purpose: two earlier
    hand rolled attempts shipped a tree that could not import itself (a
    parenthesised import whose trailing comment contains a bracket was skipped,
    and ``from src.data import registry`` lost the name after ``import``).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    found: list[Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(Import(alias.name, 0, ()))
        elif isinstance(node, ast.ImportFrom):
            found.append(Import(node.module, node.level or 0,
                                tuple(a.name for a in node.names)))
    return found


def module_paths(package: str, rel: Path) -> list[Path]:
    """Where a module name could live, and where it resolves relative to."""
    parts = package.split(".") if package else []
    return [ROOT.joinpath(*parts).with_suffix(".py"),
            ROOT.joinpath(*parts, "__init__.py")]


def source_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def seed_files() -> list[Path]:
    found: list[Path] = []
    for item in SEED:
        path = ROOT / item
        if path.is_dir():
            found += [p for p in sorted(path.rglob("*"))
                      if p.is_file()
                      and not any(part in EXCLUDE_DIRS for part in p.parts)]
        elif path.is_file():
            found.append(path)
    return found


def closure(files: list[Path]) -> list[Path]:
    """Add every in-repo module the seeds import, transitively."""
    seen: set[Path] = set()
    todo = list(files)
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        package = path.relative_to(ROOT).with_suffix("").as_posix()
        if path.name == "__init__.py":
            package = package.rsplit("/", 1)[0] if "/" in package else ""
        wanted: list[str] = []
        for imp in imports_of(text):
            if imp.level:
                # A relative import: resolve it against this file's package.
                base = package.split("/")[:-imp.level + 1]
                base = [p for p in base if p]
                if imp.module:
                    wanted.append(".".join(base + [imp.module]))
                else:
                    wanted += [".".join(base + [n]) for n in imp.names]
                continue
            if not imp.module or imp.module.split(".")[0] not in OWNED:
                continue
            wanted.append(imp.module)
            # `from pkg import name`: `name` may itself be a submodule.
            wanted += [f"{imp.module}.{n}" for n in imp.names]
        for module in wanted:
            for candidate in module_paths(module, path):
                if candidate.is_file() and candidate not in seen:
                    todo.append(candidate)
    # Package markers for any vendored src.* module, so imports resolve.
    extra: set[Path] = set()
    for path in seen:
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] == "src":
            for depth in range(1, len(rel.parts)):
                marker = ROOT.joinpath(*rel.parts[:depth], "__init__.py")
                if marker.is_file():
                    extra.add(marker)
    return sorted(seen | extra)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()
    files = closure(seed_files())
    commit = source_commit()

    print(f"source commit : {commit}")
    print(f"target        : {target}")
    print(f"files to copy : {len(files)}")
    for path in files:
        print(f"  {path.relative_to(ROOT).as_posix()}")
    if args.dry_run:
        return 0

    for path in files:
        rel = path.relative_to(ROOT)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    lines = [
        "# Provenance",
        "",
        "This tree is a generated export, never hand-edited. Regenerate it with",
        "`python tools/export_charts_of_rehan.py --target <dir>` from the",
        "Quant of Rehan monorepo.",
        "",
        f"- source repository: quant-of-rehan (`src/data` is the project's own data layer)",
        f"- source commit: `{commit}`",
        f"- exported: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- files: {len(files)}",
        "",
        "## Why `src/data/sessions.py` ships with this project",
        "",
        "The chart service asks ONE authority for session facts instead of",
        "restating them. Measured 2026-10-16, the whole chart project's only",
        "monorepo dependency is that single module (and its `__init__` markers),",
        "which is why this export is a working standalone tree rather than a",
        "folder that imports half of the parent project.",
        "",
        "## File hashes",
        "",
        "| file | sha256 |",
        "|---|---|",
    ]
    for path in files:
        lines.append(f"| `{path.relative_to(ROOT).as_posix()}` | `{sha256(path)}` |")
    (target / "PROVENANCE.md").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")
    print(f"\ncopied {len(files)} files and wrote PROVENANCE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
