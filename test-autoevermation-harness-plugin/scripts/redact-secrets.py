#!/usr/bin/env python3
"""redact-secrets.py

Scan files (or stdin) for sensitive tokens and either warn or strip them.

Usage:
  python3 redact-secrets.py --mode warn  [file ...]
  python3 redact-secrets.py --mode strip [file ...]

  If no files are given, reads from stdin (and prints to stdout for strip mode).

Modes:
  warn  — report matches with file/line info; exit nonzero if any found.
  strip — replace matched text with ***REDACTED*** in-place (files) or stdout
           (stdin); exit 0.

Patterns detected:
  - Generic API keys / tokens  (key=..., token=..., secret=..., apikey=...)
  - Passwords                  (password=..., passwd=..., pwd=...)
  - JDBC / datasource URLs     (jdbc:...)
  - AWS access key IDs         (AKIA...)
  - AWS secret access keys     (base-64-ish 40-char strings after aws_secret)
  - Private key PEM blocks     (-----BEGIN ... PRIVATE KEY-----)
  - Email addresses
  - Bearer / Authorization headers

Stdlib only (re, sys, os, argparse).
"""

import re
import sys
import os
import argparse

REDACTED = "***REDACTED***"

# ---------------------------------------------------------------------------
# Pattern registry — each entry: (name, compiled_regex)
# ---------------------------------------------------------------------------
_PATTERNS = [
    # Generic key/token/secret/apikey assignments (env-var or config style)
    ("generic_token",
     re.compile(
         r'(?i)(api[_\-]?key|token|secret|auth)["\s]*[=:]["\s]*([A-Za-z0-9+/._\-]{8,})',
         re.IGNORECASE,
     )),
    # Password assignments
    ("password",
     re.compile(
         r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']{4,})',
         re.IGNORECASE,
     )),
    # JDBC connection strings
    ("jdbc_url",
     re.compile(
         r'jdbc:[a-zA-Z0-9+\-]+://[^\s"\']+',
     )),
    # AWS access key IDs (AKIA...)
    ("aws_access_key_id",
     re.compile(
         r'\b(AKIA[0-9A-Z]{16})\b',
     )),
    # AWS secret access keys (common pattern: 40-char base64-like after label)
    ("aws_secret_access_key",
     re.compile(
         r'(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*[=:]\s*([A-Za-z0-9+/]{40})',
     )),
    # PEM private key blocks
    ("private_key_pem",
     re.compile(
         r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----',
     )),
    # Email addresses
    ("email",
     re.compile(
         r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
     )),
    # Bearer / Authorization header values
    ("bearer_token",
     re.compile(
         r'(?i)(Authorization\s*:\s*Bearer\s+)([A-Za-z0-9\-._~+/]+=*)',
     )),
]


def _find_matches(text: str):
    """Return list of (pattern_name, match_object) for all patterns."""
    hits = []
    for name, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            hits.append((name, m))
    return hits


def _redact_text(text: str) -> str:
    """Replace all sensitive matches in text with REDACTED placeholder."""
    for _name, pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _process_warn(source_name: str, text: str) -> int:
    """Print warning lines for each match. Returns number of findings."""
    hits = _find_matches(text)
    if not hits:
        return 0
    lines = text.splitlines()
    count = 0
    for name, m in hits:
        # Find line number
        lineno = text[:m.start()].count("\n") + 1
        line_preview = lines[lineno - 1].strip()[:120]
        print(f"WARN [{source_name}:{lineno}] pattern={name}: {line_preview}",
              file=sys.stderr)
        count += 1
    return count


def _process_strip_file(path: str) -> int:
    """Redact file in-place. Returns number of replacements made."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            original = fh.read()
    except OSError as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        return 0

    redacted = _redact_text(original)
    count = original.count(REDACTED)  # rough: count new markers
    # More accurate: count differences
    if redacted == original:
        return 0

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(redacted)
    except OSError as exc:
        print(f"ERROR: cannot write {path}: {exc}", file=sys.stderr)
        return 0

    # Count actual replacements by comparing
    n = sum(1 for _, pattern in _PATTERNS
            for _ in pattern.finditer(original))
    return n


def main():
    parser = argparse.ArgumentParser(
        description="Scan for and optionally redact sensitive tokens in files."
    )
    parser.add_argument(
        "--mode",
        choices=["warn", "strip"],
        required=True,
        help="warn: report matches; strip: replace with ***REDACTED***",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files to process. Reads stdin if omitted.",
    )
    args = parser.parse_args()

    total_findings = 0

    if args.files:
        for path in args.files:
            if not os.path.isfile(path):
                print(f"SKIP: not a file: {path}", file=sys.stderr)
                continue
            if args.mode == "warn":
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError as exc:
                    print(f"ERROR: {path}: {exc}", file=sys.stderr)
                    continue
                total_findings += _process_warn(path, text)
            else:  # strip
                total_findings += _process_strip_file(path)
    else:
        # stdin mode
        text = sys.stdin.read()
        if args.mode == "warn":
            total_findings += _process_warn("<stdin>", text)
        else:
            sys.stdout.write(_redact_text(text))

    if args.mode == "warn" and total_findings > 0:
        print(f"redact-secrets: {total_findings} sensitive pattern(s) found.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
