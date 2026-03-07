#!/usr/bin/env python3
"""Validate that repository text files are UTF-8 without BOM."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".css",
    ".env",
    ".example",
    ".go",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".sql",
    ".svg",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {
    ".editorconfig",
    ".gitignore",
    "Dockerfile",
    "Makefile",
}
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "agent_runs",
    "bin",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "vendor",
    "venv",
}
SUSPICIOUS_MARKERS = {
    "\ufffd": "contains Unicode replacement character",
}


@dataclass(frozen=True)
class Failure:
    path: Path
    reason: str


def should_check(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False

    if path.name in TEXT_FILENAMES:
        return True

    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True

    if path.name.endswith(".env.example"):
        return True

    return False


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if should_check(relative):
            files.append(path)
    return sorted(files)


def validate_file(path: Path, root: Path) -> list[Failure]:
    failures: list[Failure] = []
    relative = path.relative_to(root)
    data = path.read_bytes()

    if data.startswith(b"\xef\xbb\xbf"):
        failures.append(Failure(relative, "UTF-8 BOM is not allowed"))
        return failures

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        failures.append(Failure(relative, f"invalid UTF-8 at byte {exc.start}"))
        return failures

    for marker, reason in SUSPICIOUS_MARKERS.items():
        if marker in text:
            failures.append(Failure(relative, reason))

    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"repository root to scan (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print each checked file",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    files = iter_text_files(root)
    failures: list[Failure] = []

    for path in files:
        if args.verbose:
            print(f"[CHECK] {path.relative_to(root)}")
        failures.extend(validate_file(path, root))

    if failures:
        print("Encoding check failed:")
        for failure in failures:
            print(f"  - {failure.path}: {failure.reason}")
        return 1

    print(f"Encoding check passed. Checked {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
