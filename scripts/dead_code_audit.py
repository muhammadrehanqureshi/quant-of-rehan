#!/usr/bin/env python3
"""Dead-code audit with evidence: unreferenced modules, defs and imports.

Rebuild 2026-10-10. This exists because the first attempt at "remove the dead
code" deleted modules that live code imports, and broke the scanner. Removal is
a decision, so this tool only ever REPORTS; nothing is deleted automatically.

What it proves, and how:

  1. UNREFERENCED MODULE -- no file in the repository outside the module itself
     mentions its dotted path or its stem. That means no import, no `python -m`
     invocation, no workflow step, no script, no document.
  2. UNREFERENCED DEF     -- a module-level function or class whose name appears
     nowhere else in the repository AND nowhere else in its own file. The
     "nowhere else in its own file" half is what stops it flagging a helper that
     is used privately.
  3. UNUSED IMPORT        -- an imported name that never appears again in the
     file that imports it.

A hit is evidence, not a licence: a name can still be reached dynamically, by a
framework convention, or from outside the repository. Read every hit before
removing anything, and keep the test suite green afterwards.

Usage:
    python scripts/dead_code_audit.py
    python scripts/dead_code_audit.py --root src
    python scripts/dead_code_audit.py --quiet      # counts only, exit 1 on hits
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE_ROOTS = ("src", "scripts")
CORPUS_ROOTS = ("src", "scripts", "tests", "cloud", ".github", "android")
CORPUS_SUFFIXES = (".py", ".yml", ".yaml", ".js", ".java", ".md", ".toml",
                   ".xml", ".json", ".cmd", ".bat", ".sh")
EXTRA_FILES = ("README.md", "GOVERNANCE.md", "DATA_SOURCING.md",
               "INTRADAY_FORWARD_SYSTEM.md", "PROJECT_REPORT.md",
               "wrangler.toml")


def corpus() -> list[Path]:
    files: list[Path] = []
    for name in CORPUS_ROOTS:
        base = ROOT / name
        if base.is_dir():
            files += [p for p in base.rglob("*")
                      if p.is_file() and p.suffix in CORPUS_SUFFIXES]
    files += [ROOT / name for name in EXTRA_FILES if (ROOT / name).is_file()]
    return files


def text_of(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def mentions(name: str, files: list[Path], skip: Path | None = None) -> list[str]:
    """Files, other than `skip`, whose text mentions `name` as a whole word."""
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    found = []
    for candidate in files:
        if skip is not None and candidate == skip:
            continue
        if pattern.search(text_of(candidate)):
            found.append(str(candidate.relative_to(ROOT)))
    return found


def module_hits(files: list[Path], source_roots: tuple[str, ...]) -> list[tuple]:
    hits = []
    for root in source_roots:
        base = ROOT / root
        if not base.is_dir():
            continue
        for module in sorted(base.rglob("*.py")):
            dotted = ".".join(module.relative_to(ROOT).with_suffix("").parts)
            found = set(mentions(dotted, files)) | set(mentions(module.stem, files,
                                                               skip=module))
            if not found:
                hits.append((str(module.relative_to(ROOT)),
                             len(text_of(module).splitlines()), "module"))
    return hits


def def_hits(files: list[Path], source_roots: tuple[str, ...]) -> list[tuple]:
    hits = []
    for root in source_roots:
        base = ROOT / root
        if not base.is_dir():
            continue
        for module in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(text_of(module))
            except SyntaxError:
                continue
            text = text_of(module)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef)):
                    continue
                if node.name.startswith("__"):
                    continue
                if mentions(node.name, files, skip=module):
                    continue
                # its own file must not use it either (beyond the definition)
                own = len(re.findall(rf"\b{re.escape(node.name)}\b", text)) - 1
                if own <= 0:
                    hits.append((f"{module.relative_to(ROOT)}:{node.lineno}",
                                 node.name, "def"))
    return hits


def import_hits(source_roots: tuple[str, ...]) -> list[tuple]:
    """Imported names that never appear again in the importing file.

    The import statements are removed by their AST line ranges, not by a
    regex over whole lines. The regex version blanked a line only when it
    started with ``from`` or ``import``, so a name inside a parenthesised
    multi-line import kept counting as a use of itself. That blind spot hid
    five genuinely unused imports (for example ``KARACHI`` in
    scripts/kmiall_tick.py), which is exactly the kind of dead import this
    tool exists to find.
    """
    hits = []
    for root in source_roots:
        base = ROOT / root
        if not base.is_dir():
            continue
        for module in sorted(base.rglob("*.py")):
            text = text_of(module)
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            imports: list[tuple[str, int, ast.AST]] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.asname or alias.name.split(".")[0]
                             for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [alias.asname or alias.name for alias in node.names
                             if alias.name != "*"]
                else:
                    continue
                for name in names:
                    imports.append((name, node.lineno, node))

            lines = text.splitlines()
            for _, _, node in imports:
                for index in range(node.lineno - 1,
                                   getattr(node, "end_lineno", node.lineno)):
                    lines[index] = ""
            body = "\n".join(lines)
            for name, lineno, _ in imports:
                if name == "annotations":
                    continue
                if not re.search(rf"\b{re.escape(name)}\b", body):
                    hits.append((f"{module.relative_to(ROOT)}:{lineno}",
                                 name, "import"))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dead-code audit")
    parser.add_argument("--root", action="append",
                        help="source root to scan (default src and scripts)")
    parser.add_argument("--quiet", action="store_true",
                        help="print counts only; exit 1 when anything is found")
    args = parser.parse_args(argv)

    source_roots = tuple(args.root) if args.root else SOURCE_ROOTS
    files = corpus()

    modules = module_hits(files, source_roots)
    defs = def_hits(files, source_roots)
    imports = import_hits(source_roots)

    if not args.quiet:
        print(f"corpus: {len(files)} files across {', '.join(CORPUS_ROOTS)}")
        print(f"scanning: {', '.join(source_roots)}\n")

        print(f"UNREFERENCED MODULES ({len(modules)})")
        for path, lines, _ in modules:
            print(f"  {path}  ({lines} lines)")
        if not modules:
            print("  none: every module is referenced by something else")
        if modules:
            print("  note: a CLI entry point nothing imports lands here by design; "
                  "check before treating it as dead")

        print(f"\nUNREFERENCED DEFS ({len(defs)})")
        for location, name, _ in defs:
            print(f"  {location}  {name}")
        if not defs:
            print("  none: every def is used from its own file or another")

        print(f"\nUNUSED IMPORTS ({len(imports)})")
        for location, name, _ in imports:
            print(f"  {location}  {name}")
        if not imports:
            print("  none")

        print("\nRemoval is still a decision: read each hit before deleting, and "
              "keep the suite green.")

    total = len(modules) + len(defs) + len(imports)
    if args.quiet:
        print(f"modules={len(modules)} defs={len(defs)} imports={len(imports)}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
