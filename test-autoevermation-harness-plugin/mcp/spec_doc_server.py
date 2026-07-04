"""
spec-doc MCP server — Spring Test Harness Plugin
Indexes specification documents and extracts acceptance criteria for testing.

Requirements:
- Python 3.10+
- mcp package (python3 -m pip install -r mcp/requirements.txt)
- stdlib only for parsing/IO (no heavy deps)

Environment variables:
  SPEC_DOC_ALLOWLIST  comma-separated directory names allowed to index (e.g. "docs,specs,requirements")
  SPEC_DOC_REDACT     "off" to disable secret redaction; default is on
  SPEC_DOC_WORKSPACE  workspace root path; paths outside this root are rejected
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # clearer startup diagnostic than a raw traceback
    import sys

    sys.stderr.write(
        "test-autoevermation-harness-plugin spec-doc: the 'mcp' package is not importable by this "
        f"interpreter ({sys.executable}).\n"
        "Install it into the SAME python3 that Claude Code launches:\n"
        "  python3 -m pip install -r mcp/requirements.txt\n"
        f"(original error: {exc})\n"
    )
    raise

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP("spec-doc")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

def _get_workspace_root() -> Path | None:
    ws = os.environ.get("SPEC_DOC_WORKSPACE", "")
    if ws:
        return Path(ws).resolve()
    return None


def _get_allowlist() -> list[str]:
    raw = os.environ.get("SPEC_DOC_ALLOWLIST", "docs,specs,requirements,spec,doc,requirement")
    return [d.strip() for d in raw.split(",") if d.strip()]


def _redact_enabled() -> bool:
    return os.environ.get("SPEC_DOC_REDACT", "on").lower() != "off"


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

_REDACT_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # AWS access keys
    ("AWS_KEY", re.compile(r"\b(AKIA|ASIA|AROA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    # AWS secret keys (40-char base64-like after key= or secret=)
    ("AWS_SECRET", re.compile(
        r'(?i)(aws[_\-]?secret[_\-]?access[_\-]?key\s*[=:]\s*)[A-Za-z0-9+/]{40}'
    ), r"\1[REDACTED_AWS_SECRET]"),
    # PEM private keys
    ("PEM", re.compile(
        r"-----BEGIN[^-]*PRIVATE KEY-----[\s\S]*?-----END[^-]*PRIVATE KEY-----",
        re.MULTILINE,
    ), "[REDACTED_PEM_KEY]"),
    # Generic passwords/tokens in key=value or key: value patterns
    ("PASSWORD", re.compile(
        r'(?i)(password|passwd|pwd|secret|token|api[_\-]?key|auth[_\-]?token|bearer)'
        r'(\s*[=:]\s*)[\'"]?[A-Za-z0-9+/!@#$%^&*()\-_=+|;:,.<>?`~]{8,}[\'"]?'
    ), r"\1\2[REDACTED_SECRET]"),
    # JDBC / connection strings
    ("JDBC", re.compile(
        r'(?i)jdbc:[a-z]+://[^\s\'"<>]+'
    ), "[REDACTED_JDBC_URL]"),
    # Generic connection strings with passwords
    ("CONNSTR", re.compile(
        r'(?i)(connection[_\-]?string|connstr|dsn)\s*[=:]\s*[\'"]?[^\s\'"<>]{10,}[\'"]?'
    ), r"\1=[REDACTED_CONNSTR]"),
    # Email addresses
    ("EMAIL", re.compile(
        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
    ), "[REDACTED_EMAIL]"),
]


def redact_text(text: str) -> str:
    """Apply all redaction patterns to the text and return sanitized version."""
    if not _redact_enabled():
        return text
    result = text
    for _name, pattern, replacement in _REDACT_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------

def _is_path_allowed(path: Path) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    A path is allowed if:
    1. It is within the workspace root (if set), AND
    2. One of its ancestor directory names is in the allowlist.
    """
    resolved = path.resolve()

    # Check workspace root
    workspace_root = _get_workspace_root()
    if workspace_root is not None:
        try:
            resolved.relative_to(workspace_root)
        except ValueError:
            return False, f"Path outside workspace root: {resolved}"

    # Check allowlist: at least one path component must match
    allowlist = _get_allowlist()
    if allowlist:
        parts_lower = {p.lower() for p in resolved.parts}
        if not any(allowed.lower() in parts_lower for allowed in allowlist):
            return False, (
                f"Path not under any allowed directory {allowlist}: {resolved}"
            )

    return True, ""


def _safe_read(path: Path) -> tuple[str | None, str | None]:
    """Read a file safely; returns (content, error_message)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(), None
    except PermissionError:
        return None, f"SPEC_DOC_UNREADABLE: permission denied: {path}"
    except OSError as exc:
        return None, f"SPEC_DOC_UNREADABLE: {exc}: {path}"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".adoc", ".rst", ".text"}
_CHUNK_SIZE = 1200   # characters per chunk (roughly)
_CHUNK_OVERLAP = 150  # overlap to preserve context across boundaries


def _chunk_text(text: str, source: str) -> list[dict[str, Any]]:
    """Split text into overlapping chunks with metadata."""
    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_index = 0
    length = len(text)
    while start < length:
        end = min(start + _CHUNK_SIZE, length)
        chunk_text = text[start:end]
        chunk_id = f"{hashlib.md5((source + str(chunk_index)).encode()).hexdigest()[:8]}"
        chunks.append({
            "id": chunk_id,
            "source": source,
            "chunk_index": chunk_index,
            "text": chunk_text,
        })
        chunk_index += 1
        if end >= length:
            break
        start = end - _CHUNK_OVERLAP
    return chunks


# ---------------------------------------------------------------------------
# In-memory index
# ---------------------------------------------------------------------------

# Global index: list of chunk dicts
_INDEX: list[dict[str, Any]] = []
# Glossary extracted from indexed docs
_GLOSSARY: dict[str, str] = {}
# Requirement matrix: doc -> list of requirement headings
_REQUIREMENT_MATRIX: dict[str, list[str]] = {}


def _clear_index() -> None:
    _INDEX.clear()
    _GLOSSARY.clear()
    _REQUIREMENT_MATRIX.clear()


def _build_glossary_from_chunks(chunks: list[dict[str, Any]]) -> dict[str, str]:
    """Extract simple term: definition pairs from text using heuristics."""
    glossary: dict[str, str] = {}
    # Patterns: "**Term**: definition" or "- Term: definition" or "Term — definition"
    term_patterns = [
        re.compile(r"\*\*([^*]{2,40})\*\*\s*[:：]\s*(.{10,200})", re.MULTILINE),
        re.compile(r"^[-*]\s+([A-Za-z가-힣][^:：\n]{1,39})\s*[:：]\s*(.{10,200})", re.MULTILINE),
        re.compile(r"^([A-Za-z가-힣][^—\n]{1,39})\s+[—–]\s+(.{10,200})", re.MULTILINE),
    ]
    for chunk in chunks:
        text = chunk["text"]
        for pattern in term_patterns:
            for match in pattern.finditer(text):
                term = match.group(1).strip()
                definition = match.group(2).strip()
                if term and definition and term not in glossary:
                    glossary[term] = definition[:200]
    return glossary


def _extract_requirement_headings(text: str) -> list[str]:
    """Extract markdown/adoc headings that look like requirements."""
    headings: list[str] = []
    # Markdown headings
    for match in re.finditer(r"^#{1,4}\s+(.+)$", text, re.MULTILINE):
        heading = match.group(1).strip()
        # Keep headings that look like requirements (contain must/shall/요구/기능/제약/given/when/then)
        if re.search(
            r"(?i)(must|shall|should|요구|기능|제약|조건|given|when|then|requirement|spec|criteria)",
            heading,
        ):
            headings.append(heading)
    # AsciiDoc headings (== Title)
    for match in re.finditer(r"^={1,5}\s+(.+)$", text, re.MULTILINE):
        heading = match.group(1).strip()
        if re.search(
            r"(?i)(must|shall|should|요구|기능|제약|조건|given|when|then|requirement|spec|criteria)",
            heading,
        ):
            headings.append(heading)
    return headings


# ---------------------------------------------------------------------------
# Keyword scoring for search
# ---------------------------------------------------------------------------

def _score_chunk(chunk: dict[str, Any], query_tokens: list[str]) -> float:
    """Score a chunk against query tokens (simple TF-based)."""
    text_lower = chunk["text"].lower()
    score = 0.0
    for token in query_tokens:
        # Count whole-word occurrences (word-boundary aware so "id" does not
        # match inside "valid"/"identity"). Falls back to plain count for tokens
        # with no word characters (e.g. punctuation-only).
        tok = token.lower()
        if re.search(r"\w", tok):
            count = len(re.findall(r"\b" + re.escape(tok) + r"\b", text_lower))
        else:
            count = text_lower.count(tok)
        if count > 0:
            # +1 for presence, log-weighted frequency
            score += 1.0 + min(count - 1, 4) * 0.2
    return score


# ---------------------------------------------------------------------------
# Acceptance criteria extraction
# ---------------------------------------------------------------------------

def _extract_gherkin_blocks(text: str, source: str) -> list[dict[str, Any]]:
    """Extract Given/When/Then blocks from text.

    Handles three real-world markdown shapes, not just bare Gherkin:
    - ``Scenario:``/``시나리오:`` header followed by keyword lines (classic)
    - headerless blocks of consecutive Given/When/Then lines
    - markdown bullets (``- Given ...``) and single-line inline form
      (``Given X, When Y, Then Z``) — normalized before matching
    """
    criteria: list[dict[str, Any]] = []
    # Normalize: strip markdown bullet/number prefixes so "- Given ..." matches,
    # then split inline "Given X, When Y, Then Z" onto separate lines.
    norm = re.sub(r"(?m)^([ \t]*)(?:[-*+]|\d+[.)])[ \t]+", r"\1", text)
    norm = re.sub(r"(?i)[,;][ \t]*(when|then|and|but|했을때|그러면|그리고)\b", r"\n\1", norm)

    _KW_LINE = r"[ \t]*(?:given|when|then|and|but|주어진|그러면|했을때|그리고)\b[^\n]*\n?"
    # Pass 1: blocks introduced by a Scenario/Feature header (title preserved)
    scenario_pattern = re.compile(
        r"(?i)(?:scenario|시나리오|feature|기능)[:\s]+([^\n]+)\n"
        rf"((?:{_KW_LINE})+)",
        re.MULTILINE,
    )
    # Pass 2: headerless GWT blocks — 2+ consecutive keyword lines
    bare_pattern = re.compile(rf"(?im)^((?:{_KW_LINE}){{2,}})")

    blocks: list[tuple[str, str]] = []
    consumed: list[tuple[int, int]] = []
    for m in scenario_pattern.finditer(norm):
        blocks.append((m.group(1).strip(), m.group(2)))
        consumed.append(m.span())
    for m in bare_pattern.finditer(norm):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        blocks.append(("", m.group(1)))

    for i, (title, block) in enumerate(blocks):
        given_parts: list[str] = []
        when_parts: list[str] = []
        then_parts: list[str] = []
        current = "given"
        for line in block.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            lower_line = line_stripped.lower()
            if re.match(r"(given|주어진)", lower_line):
                current = "given"
                given_parts.append(re.sub(r"(?i)^(given|주어진)\s*", "", line_stripped).strip())
            elif re.match(r"(when|했을때)", lower_line):
                current = "when"
                when_parts.append(re.sub(r"(?i)^(when|했을때)\s*", "", line_stripped).strip())
            elif re.match(r"(then|그러면)", lower_line):
                current = "then"
                then_parts.append(re.sub(r"(?i)^(then|그러면)\s*", "", line_stripped).strip())
            elif re.match(r"(and|but|그리고)", lower_line):
                text_part = re.sub(r"(?i)^(and|but|그리고)\s*", "", line_stripped).strip()
                if current == "given":
                    given_parts.append(text_part)
                elif current == "when":
                    when_parts.append(text_part)
                else:
                    then_parts.append(text_part)
        if then_parts:
            if not title:
                # headerless block: derive a title from the behavior (when > then)
                title = (when_parts[0] if when_parts else then_parts[0])[:80]
            crit_id = f"AC-{hashlib.md5((source + title + str(i)).encode()).hexdigest()[:6].upper()}"
            criteria.append({
                "id": crit_id,
                "title": title,
                "given": " AND ".join(given_parts) if given_parts else "",
                "when": " AND ".join(when_parts) if when_parts else "",
                "then": " AND ".join(then_parts),
                "sourceDoc": source,
            })
    return criteria


def _extract_rule_sentences(text: str, source: str) -> list[dict[str, Any]]:
    """Extract must/shall/해야/금지 rule sentences as acceptance criteria."""
    criteria: list[dict[str, Any]] = []
    # Match sentences containing obligation keywords
    rule_pattern = re.compile(
        r"[^.。\n]*(?:must|shall|should not|must not|is required to|are required to"
        r"|해야|하여야|금지|해서는\s*안|되어서는\s*안|돼서는\s*안|하지\s*말아야|하면\s*안)[^.。\n]*[.。]?",
        re.IGNORECASE,
    )
    for i, match in enumerate(rule_pattern.finditer(text)):
        sentence = match.group(0).strip()
        # strip a leading markdown bullet/number so the criterion reads as a sentence
        sentence = re.sub(r"^(?:[-*+]|\d+[.)])[ \t]+", "", sentence)
        if len(sentence) < 10:
            continue
        crit_id = f"RULE-{hashlib.md5((source + sentence).encode()).hexdigest()[:6].upper()}"
        # Distinguish prohibition from requirement
        is_prohibition = bool(re.search(
            r"(?i)(must not|should not|shall not|금지|해서는\s*안|되어서는\s*안|돼서는\s*안|하지\s*말아야|하면\s*안)",
            sentence,
        ))
        criteria.append({
            "id": crit_id,
            "title": sentence[:100],
            "given": "",
            "when": "",
            "then": sentence,
            "isProhibition": is_prohibition,
            "sourceDoc": source,
        })
    return criteria


def _strip_prohibition(crit: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a criterion without the internal isProhibition flag."""
    return {k: v for k, v in crit.items() if k != "isProhibition"}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def index_docs(paths: list[str]) -> dict:
    """
    Walk the provided paths (files or directories), read .md/.txt/.adoc files,
    chunk them, and build an in-memory index.

    Respects SPEC_DOC_ALLOWLIST (comma-separated directory names) and rejects
    paths outside the workspace root (SPEC_DOC_WORKSPACE).
    Unreadable documents are reported as SPEC_DOC_UNREADABLE in the result.

    Args:
        paths: List of file paths or directory paths to index.

    Returns:
        dict with keys: status, indexed_files, chunk_count, unreadable, warnings, errors
    """
    _clear_index()
    indexed_files: list[str] = []
    unreadable: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    all_chunks: list[dict[str, Any]] = []

    def _process_file(fpath: Path, explicit: bool = False) -> None:
        if fpath.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            # A file the caller named explicitly (e.g. an advertised .pdf spec)
            # must not be dropped silently — report it so the agent knows it was
            # not ingested. Files discovered by directory scan are skipped quietly.
            if explicit:
                unreadable.append(
                    f"SPEC_DOC_UNREADABLE: unsupported file type "
                    f"'{fpath.suffix or '(none)'}' (supported: "
                    f"{', '.join(sorted(_SUPPORTED_EXTENSIONS))}): {fpath}"
                )
            return
        allowed, reason = _is_path_allowed(fpath)
        if not allowed:
            warnings.append(f"Skipped (not allowed): {fpath} — {reason}")
            return
        content, err = _safe_read(fpath)
        if err:
            unreadable.append(err)
            return
        assert content is not None
        redacted = redact_text(content)
        # Store a resolved absolute path as the source key so extract_acceptance_criteria
        # (which resolves its `paths`) matches regardless of the path form used at index
        # time (directory vs file, relative vs absolute). _is_path_allowed also resolves.
        src_key = str(fpath.resolve())
        chunks = _chunk_text(redacted, src_key)
        all_chunks.extend(chunks)
        # Collect requirement headings for matrix
        headings = _extract_requirement_headings(redacted)
        if headings:
            _REQUIREMENT_MATRIX[src_key] = headings
        indexed_files.append(src_key)

    for raw_path in paths:
        p = Path(raw_path)
        if not p.exists():
            warnings.append(f"Path does not exist: {p}")
            continue
        if p.is_file():
            _process_file(p, explicit=True)
        elif p.is_dir():
            allowed, reason = _is_path_allowed(p)
            if not allowed:
                warnings.append(f"Directory skipped (not allowed): {p} — {reason}")
                continue
            for fpath in sorted(p.rglob("*")):
                if fpath.is_file():
                    _process_file(fpath)
        else:
            warnings.append(f"Not a file or directory: {p}")

    # Build global index
    _INDEX.extend(all_chunks)

    # Build glossary from all chunks
    new_glossary = _build_glossary_from_chunks(all_chunks)
    _GLOSSARY.update(new_glossary)

    status = "ok" if indexed_files else ("partial" if unreadable else "failed")
    if not indexed_files and not unreadable:
        status = "failed"
        errors.append("No supported documents found in provided paths.")

    return {
        "status": status,
        "indexed_files": indexed_files,
        "chunk_count": len(all_chunks),
        "unreadable": unreadable,
        "warnings": warnings,
        "errors": errors,
    }


@mcp.tool()
def search_requirements(query: str, top_k: int = 10) -> dict:
    """
    Keyword/score search over indexed document chunks.

    Args:
        query: Search query string (space-separated keywords).
        top_k: Maximum number of results to return (default 10).

    Returns:
        dict with keys: status, query, results (list of chunk matches), total_chunks_searched
    """
    if not _INDEX:
        return {
            "status": "failed",
            "query": query,
            "results": [],
            "total_chunks_searched": 0,
            "errors": ["Index is empty. Call index_docs() first."],
        }

    query_tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    if not query_tokens:
        return {
            "status": "failed",
            "query": query,
            "results": [],
            "total_chunks_searched": len(_INDEX),
            "errors": ["Query is empty."],
        }

    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in _INDEX:
        score = _score_chunk(chunk, query_tokens)
        if score > 0:
            scored.append((score, chunk))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)
    # Respect the caller's limit literally: top_k<=0 returns no results.
    top = scored[:top_k] if top_k > 0 else []

    results = []
    for score, chunk in top:
        results.append({
            "score": round(score, 3),
            "chunk_id": chunk["id"],
            "source": chunk["source"],
            "chunk_index": chunk["chunk_index"],
            "text": chunk["text"],
        })

    return {
        "status": "ok",
        "query": query,
        "results": results,
        "total_chunks_searched": len(_INDEX),
    }


@mcp.tool()
def extract_acceptance_criteria(paths: list[str] | None = None) -> dict:
    """
    Heuristically extract acceptance criteria from indexed documents (or specific paths).

    Extracts:
    - Given/When/Then (Gherkin-style) scenarios
    - must/shall/해야/금지 rule sentences

    Normalizes into acceptanceCriteria[] with ids and sourceDoc.
    Separates prohibitions[] from positive requirements.

    Args:
        paths: Optional list of specific source paths to extract from.
               If None, extracts from all indexed chunks.

    Returns:
        SpecReviewResult dict: status, summary, requirements[], acceptanceCriteria[],
                               prohibitions[], glossary, evidence[], warnings[], errors[]
    """
    if not _INDEX:
        return {
            "status": "failed",
            "summary": "Index is empty. Call index_docs() first.",
            "requirements": [],
            "acceptanceCriteria": [],
            "prohibitions": [],
            "glossary": {},
            "evidence": [],
            "warnings": [],
            "errors": ["Index is empty. Call index_docs() first."],
        }

    # Determine which sources to process
    if paths:
        target_sources = {str(Path(p).resolve()) for p in paths}
        # Also match by non-resolved path string for flexibility
        target_sources_raw = {str(p) for p in paths}
    else:
        target_sources = None
        target_sources_raw = None

    # Group chunks by source
    source_to_text: dict[str, list[str]] = {}
    for chunk in _INDEX:
        src = chunk["source"]
        if target_sources is not None:
            if src not in target_sources and src not in target_sources_raw:  # type: ignore[operator]
                continue
        source_to_text.setdefault(src, []).append(chunk["text"])

    all_criteria: list[dict[str, Any]] = []
    prohibitions: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    warnings: list[str] = []

    for src, texts in source_to_text.items():
        full_text = "\n".join(texts)

        # Gherkin blocks
        gherkin = _extract_gherkin_blocks(full_text, src)
        for crit in gherkin:
            if crit["id"] not in seen_ids:
                seen_ids.add(crit["id"])
                all_criteria.append(crit)

        # Rule sentences
        rules = _extract_rule_sentences(full_text, src)
        for rule in rules:
            if rule["id"] not in seen_ids:
                seen_ids.add(rule["id"])
                all_criteria.append(rule)

    if not all_criteria and not source_to_text:
        warnings.append("No matching sources found in index for the provided paths.")

    # Separate positive criteria from prohibitions (drop the internal isProhibition flag).
    for crit in all_criteria:
        target = prohibitions if crit.get("isProhibition") else requirements
        target.append(_strip_prohibition(crit))

    # acceptance_criteria is union of all (positive + negative)
    acceptance_criteria = [_strip_prohibition(c) for c in all_criteria]

    summary = (
        f"Extracted {len(acceptance_criteria)} acceptance criteria "
        f"({len(requirements)} requirements, {len(prohibitions)} prohibitions) "
        f"from {len(source_to_text)} source(s)."
    )

    return {
        "status": "ok" if acceptance_criteria else "partial",
        "summary": summary,
        "requirements": requirements,
        "acceptanceCriteria": acceptance_criteria,
        "prohibitions": prohibitions,
        "glossary": dict(_GLOSSARY),
        "evidence": [f"Processed {len(source_to_text)} source document(s)."],
        "warnings": warnings,
        "errors": [],
        "nextActions": (
            ["Review extracted criteria with domain expert."] if acceptance_criteria else
            ["Verify document paths and re-run index_docs() with correct allowlist."]
        ),
    }


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("spec://glossary")
def get_glossary() -> str:
    """
    Returns the glossary of domain terms extracted from indexed specification documents.
    Format: JSON-like text with term: definition pairs.
    """
    if not _GLOSSARY:
        return (
            "# Spec Glossary\n\n"
            "No glossary entries available. Run index_docs() first to populate the index.\n"
        )
    lines = ["# Spec Glossary\n"]
    for term, definition in sorted(_GLOSSARY.items(), key=lambda x: x[0].lower()):
        lines.append(f"**{term}**: {definition}\n")
    return "\n".join(lines)


@mcp.resource("spec://requirement-matrix")
def get_requirement_matrix() -> str:
    """
    Returns the requirement matrix: a mapping of source documents to their
    requirement-related headings, extracted during indexing.
    """
    if not _REQUIREMENT_MATRIX:
        return (
            "# Requirement Matrix\n\n"
            "No requirements indexed yet. Run index_docs() first.\n"
        )
    lines = ["# Requirement Matrix\n"]
    for doc, headings in sorted(_REQUIREMENT_MATRIX.items()):
        lines.append(f"## {doc}\n")
        for h in headings:
            lines.append(f"- {h}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def review_specs_for_testing(spec_paths: str = "", domain_keywords: str = "") -> str:
    """
    Prompt template for reviewing specification documents for testability.

    Args:
        spec_paths: Comma-separated list of specification document paths.
        domain_keywords: Comma-separated domain keywords to focus on.
    """
    paths_section = (
        f"Specification paths to review:\n{spec_paths}"
        if spec_paths
        else "Use all currently indexed specification documents."
    )
    keywords_section = (
        f"\nFocus domain keywords: {domain_keywords}"
        if domain_keywords
        else ""
    )
    return f"""You are a test specification reviewer. Your task is to analyze specification
documents and extract acceptance criteria suitable for test case generation.

{paths_section}{keywords_section}

## Instructions

1. Call `index_docs(paths=[...])` to index the specification documents listed above.
   - If a document is unreadable, report it as SPEC_DOC_UNREADABLE and continue.

2. Call `extract_acceptance_criteria()` to extract all acceptance criteria.
   - Normalize Gherkin-style (Given/When/Then) scenarios.
   - Extract must/shall/해야/금지 obligation sentences as rules.
   - Separate prohibitions from positive requirements.

3. Call `search_requirements(query="...")` for key domain terms to find related sections.

4. Return a SpecReviewResult JSON with:
   - status: "ok" | "partial" | "failed"
   - summary: concise description of what was found
   - requirements[]: positive acceptance criteria with id, given, when, then, sourceDoc
   - acceptanceCriteria[]: all criteria (union of requirements and prohibitions)
   - prohibitions[]: negative/forbidden conditions
   - glossary: domain term definitions extracted from documents
   - evidence[]: list of supporting sources
   - warnings[]: issues encountered (unreadable docs, etc.)
   - errors[]: blocking errors
   - nextActions[]: recommended follow-up steps

## Quality Rules

- Do NOT skip any requirement heading or obligation sentence.
- Assign a unique id to each criterion (format: AC-XXXXXX or RULE-XXXXXX).
- Always include sourceDoc for traceability.
- Redaction is applied automatically — do not attempt to recover masked values.
- No network access is permitted during this review.
- Report every unreadable document explicitly with path and reason.
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point: run the spec-doc server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
