#!/usr/bin/env python3
"""repo-ast MCP server.

A FastMCP (official MCP Python SDK) server that performs *structure-only* Java
AST/symbol analysis for the Spring test-harness plugin.

Design contract (see RESEARCH_NOTES.md sections 1-2 and REPORT.md):

* High-level API: ``from mcp.server.fastmcp import FastMCP`` with ``@mcp.tool()``,
  ``@mcp.resource()`` and ``@mcp.prompt()`` decorators; stdio transport.
* Java AST is produced by a bundled JavaParser symbol-solver CLI jar invoked via
  ``subprocess`` returning JSON. When the jar or a JDK is unavailable the server
  *degrades gracefully* to a pure-Python regex extractor, sets ``degraded: true``
  and records what could not be resolved in ``unresolvedSymbols``.
* Output conforms to the ``AstAnalysisResult`` schema:
  ``status``/``summary``/``testTargets[]``/``dependencyGraph``/
  ``unresolvedSymbols[]``/``riskPoints[]``/``evidence``/``warnings``/``errors``/
  ``nextActions``.
* SECURITY: never returns method *bodies* (only signatures / annotations /
  metadata); enforces a path allowlist rooted at ``REPO_AST_ALLOW_ROOT``; performs
  no network access.

The module is import-safe: importing it (or running ``py_compile``) must not
require the ``mcp`` package to be installed. The pure-Python fallback works
without the Java jar so the server is usable immediately.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

try:  # pragma: no cover - import shim so py_compile/tests work without the SDK
    from mcp.server.fastmcp import FastMCP
except Exception:  # noqa: BLE001 - any import failure should not crash module load
    FastMCP = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Constants / configuration
# ---------------------------------------------------------------------------

SERVER_NAME = "repo-ast"

#: Spring stereotype annotations -> coarse target kind.
SPRING_STEREOTYPES: dict[str, str] = {
    "RestController": "controller",
    "Controller": "controller",
    "Service": "service",
    "Repository": "repository",
    "Component": "component",
    "Configuration": "component",
    "ControllerAdvice": "controller",
    "RestControllerAdvice": "controller",
}

VALID_KINDS = {"controller", "service", "repository", "component", "pojo", "unknown"}

#: Annotations that hint a JPA repository even without an explicit stereotype.
JPA_REPOSITORY_HINTS = (
    "JpaRepository",
    "CrudRepository",
    "PagingAndSortingRepository",
    "Repository",
)


# ---------------------------------------------------------------------------
# Path allowlist / security
# ---------------------------------------------------------------------------


def _allow_root() -> Optional[Path]:
    """Return the configured allowlist root, or ``None`` if unset."""
    raw = os.environ.get("REPO_AST_ALLOW_ROOT", "").strip()
    if not raw:
        return None
    try:
        return Path(raw).resolve()
    except Exception:  # noqa: BLE001
        return None


def _is_allowed(path: Path, root: Optional[Path]) -> bool:
    """True when ``path`` resolves inside ``root`` (or no root is configured)."""
    try:
        resolved = path.resolve()
    except Exception:  # noqa: BLE001
        return False
    if root is None:
        # No allowlist configured: refuse to walk outside the current working
        # directory to stay conservative ("no network, path allowlist").
        root = Path.cwd().resolve()
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False


def _collect_java_files(paths: list[str], root: Optional[Path]) -> tuple[list[Path], list[str]]:
    """Expand the requested paths into allowed ``*.java`` files.

    Returns ``(files, denied)`` where ``denied`` lists string paths rejected by
    the allowlist or that do not exist.
    """
    files: list[Path] = []
    denied: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        if not _is_allowed(p, root):
            denied.append(raw)
            continue
        if not p.exists():
            denied.append(raw)
            continue
        candidates: list[Path]
        if p.is_dir():
            candidates = sorted(p.rglob("*.java"))
        elif p.suffix == ".java":
            candidates = [p]
        else:
            candidates = []
        for c in candidates:
            if not _is_allowed(c, root):
                denied.append(str(c))
                continue
            key = str(c.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(c)
    return files, denied


# ---------------------------------------------------------------------------
# JavaParser CLI jar discovery
# ---------------------------------------------------------------------------


def _locate_jar() -> Optional[str]:
    """Locate the JavaParser CLI shaded jar.

    Resolution order:
    1. ``REPO_AST_JAVAPARSER_JAR`` env var (explicit path).
    2. ``mcp/javaparser-cli/target/*.jar`` relative to this file.
    """
    env_jar = os.environ.get("REPO_AST_JAVAPARSER_JAR", "").strip()
    if env_jar and Path(env_jar).is_file():
        return env_jar

    here = Path(__file__).resolve().parent
    target_dir = here / "javaparser-cli" / "target"
    # Prefer a shaded ("*-shaded.jar" / "*-with-dependencies.jar") artifact.
    patterns = ["*-shaded.jar", "*-jar-with-dependencies.jar", "*.jar"]
    for pattern in patterns:
        matches = sorted(glob.glob(str(target_dir / pattern)))
        # Skip the thin "original-" artifacts produced by the shade plugin.
        matches = [m for m in matches if not Path(m).name.startswith("original-")]
        if matches:
            return matches[0]
    return None


def _jdk_available() -> bool:
    """Return True when a ``java`` runtime can be invoked."""
    java = os.environ.get("REPO_AST_JAVA_BIN", "java")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed args, no shell
            [java, "-version"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _run_java_cli(jar: str, target: Path) -> Optional[dict[str, Any]]:
    """Invoke the JavaParser CLI jar and parse its JSON output.

    Returns the parsed dict, or ``None`` on any failure (caller falls back to the
    pure-Python extractor). Never raises.
    """
    java = os.environ.get("REPO_AST_JAVA_BIN", "java")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed args, no shell, env-controlled
            [java, "-jar", jar, str(target)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={**os.environ, "REPO_AST_NETWORK": "off"},
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Pure-Python fallback extractor (regex based, signatures/annotations only)
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(static\s+)?([\w.*]+)\s*;", re.MULTILINE)
_TYPE_DECL_RE = re.compile(
    r"(?P<annos>(?:@[\w.]+(?:\([^)]*\))?\s*)*)"
    r"(?:public|protected|private|abstract|final|sealed|non-sealed|static|strictfp|\s)*"
    r"(?P<typekind>class|interface|enum|record)\s+"
    r"(?P<name>[A-Za-z_]\w*)"
)
_ANNO_RE = re.compile(r"@([\w.]+)(?:\([^)]*\))?")
# Method signature: optional annotations, modifiers, return type, name, params.
_METHOD_RE = re.compile(
    r"(?P<annos>(?:@[\w.]+(?:\([^)]*\))?\s*)*)"
    r"(?P<mods>(?:public|protected|private|static|final|abstract|synchronized|"
    r"native|default|\s)*)"
    r"(?P<ret>[\w.<>,\[\]?\s]+?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<params>[^)]*)\)"
    r"(?:\s*throws\s+[\w.,\s]+)?\s*[{;]"
)
# Field: modifiers, type, name (no method parens before ; ).
_FIELD_RE = re.compile(
    r"(?P<annos>(?:@[\w.]+(?:\([^)]*\))?\s*)*)"
    r"(?P<mods>(?:public|protected|private|static|final|transient|volatile|\s)*)"
    r"(?P<type>[\w.<>,\[\]?]+)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*[=;]"
)


def _strip_comments_and_strings(source: str) -> str:
    """Remove comments and string/char literals so regexes don't trip on them.

    This intentionally collapses string contents to empty literals; it does NOT
    attempt to be a real lexer. It is only used to make the heuristic extractor
    more robust. Method *bodies* are never emitted regardless.
    """
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        two = source[i : i + 2]
        if two == "//":
            j = source.find("\n", i)
            i = n if j == -1 else j
            continue
        if two == "/*":
            j = source.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c in {'"', "'"}:
            quote = c
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            out.append('""' if quote == '"' else "''")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _short(name: str) -> str:
    """Return the simple (unqualified) name of an annotation/type."""
    return name.split(".")[-1]


def _annotations_from(blob: str) -> list[str]:
    return [_short(m.group(1)) for m in _ANNO_RE.finditer(blob or "")]


def _classify_kind(annotations: list[str], implements_blob: str) -> str:
    for anno in annotations:
        if anno in SPRING_STEREOTYPES:
            return SPRING_STEREOTYPES[anno]
    for hint in JPA_REPOSITORY_HINTS:
        if hint in implements_blob:
            return "repository"
    return "pojo"


def _normalize_params(params: str) -> str:
    parts = [p.strip() for p in params.split(",") if p.strip()]
    norm: list[str] = []
    for part in parts:
        # Drop parameter annotations, keep "type name" -> reduce to type.
        cleaned = re.sub(r"@[\w.]+(?:\([^)]*\))?", "", part).strip()
        tokens = cleaned.split()
        if len(tokens) >= 2:
            norm.append(" ".join(tokens[:-1]))  # type (may be multi-token generic)
        elif tokens:
            norm.append(tokens[0])
    return ", ".join(norm)


def _fallback_parse_file(path: Path) -> dict[str, Any]:
    """Heuristic, regex-based extraction. Never emits method bodies."""
    text = path.read_text(encoding="utf-8", errors="replace")
    cleaned = _strip_comments_and_strings(text)

    pkg_match = _PACKAGE_RE.search(cleaned)
    package = pkg_match.group(1) if pkg_match else ""
    imports = [m.group(2) for m in _IMPORT_RE.finditer(cleaned)]

    classes: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for tdecl in _TYPE_DECL_RE.finditer(cleaned):
        name = tdecl.group("name")
        type_kind = tdecl.group("typekind")
        annos = _annotations_from(tdecl.group("annos"))
        fqcn = f"{package}.{name}" if package else name

        # Capture the extends/implements clause for repository detection.
        tail = cleaned[tdecl.end() : tdecl.end() + 400]
        impl_match = re.match(r"[^{;]*", tail)
        implements_blob = impl_match.group(0) if impl_match else ""

        kind = _classify_kind(annos, implements_blob)

        methods: list[dict[str, Any]] = []
        for mm in _METHOD_RE.finditer(cleaned):
            mods = mm.group("mods") or ""
            if "public" not in mods:
                continue
            ret = " ".join(mm.group("ret").split())
            mname = mm.group("name")
            if mname in {"if", "for", "while", "switch", "catch", "return", "new"}:
                continue
            params = _normalize_params(mm.group("params"))
            signature = f"{ret} {mname}({params})".strip()
            methods.append(
                {
                    "name": mname,
                    "signature": signature,
                    "returnType": ret,
                    "annotations": _annotations_from(mm.group("annos")),
                    "modifiers": [t for t in mods.split() if t],
                }
            )

        fields: list[dict[str, Any]] = []
        for fm in _FIELD_RE.finditer(cleaned):
            ftype = fm.group("type")
            fname = fm.group("name")
            if ftype in {"return", "new", "throw"}:
                continue
            fields.append(
                {
                    "name": fname,
                    "type": ftype,
                    "annotations": _annotations_from(fm.group("annos")),
                    "modifiers": [t for t in (fm.group("mods") or "").split() if t],
                }
            )

        classes.append(
            {
                "fqcn": fqcn,
                "simpleName": name,
                "typeKind": type_kind,
                "package": package,
                "annotations": annos,
                "kind": kind,
                "methods": methods,
                "fields": fields,
                "extendsImplements": implements_blob.strip(),
            }
        )

    # Regex extraction cannot resolve symbol bindings; flag imports as the
    # universe of unresolved-but-referenced types so callers know precision is
    # reduced in this mode.
    if not classes:
        unresolved.append(f"NO_TYPE_DECL:{path.name}")

    return {
        "file": str(path),
        "package": package,
        "imports": imports,
        "classes": classes,
        "unresolvedSymbols": unresolved,
    }


# ---------------------------------------------------------------------------
# Result assembly (AstAnalysisResult)
# ---------------------------------------------------------------------------


def _empty_result() -> dict[str, Any]:
    return {
        "status": "ok",
        "summary": "",
        "degraded": False,
        "testTargets": [],
        "dependencyGraph": {"nodes": [], "edges": []},
        "unresolvedSymbols": [],
        "riskPoints": [],
        "evidence": [],
        "warnings": [],
        "errors": [],
        "nextActions": [],
    }


def _public_methods(cls: dict[str, Any]) -> list[str]:
    return [m["signature"] for m in cls.get("methods", []) if m.get("signature")]


def _risk_points_for(cls: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    fqcn = cls.get("fqcn", "?")
    field_types = " ".join(f.get("type", "") for f in cls.get("fields", []))
    method_blob = " ".join(m.get("signature", "") for m in cls.get("methods", []))
    haystack = f"{field_types} {method_blob}"
    seam_patterns = {
        "clock/time dependency": ("LocalDateTime", "LocalDate", "Instant", "Clock", "now("),
        "randomness": ("Random", "UUID", "SecureRandom"),
        "external I/O": ("RestTemplate", "WebClient", "HttpClient", "RestClient"),
        "filesystem": ("File", "Path", "InputStream", "OutputStream"),
    }
    for label, needles in seam_patterns.items():
        if any(needle in haystack for needle in needles):
            risks.append(f"{fqcn}: {label} detected (consider injectable seam/mock)")
    if cls.get("kind") == "controller" and not cls.get("methods"):
        risks.append(f"{fqcn}: controller with no detected public endpoints")
    return risks


def _build_result(
    parsed_files: list[dict[str, Any]],
    *,
    degraded: bool,
    denied: list[str],
    kinds_filter: Optional[list[str]],
    parse_mode: str,
) -> dict[str, Any]:
    result = _empty_result()
    result["degraded"] = degraded

    nodes: list[str] = []
    edges: list[dict[str, str]] = []
    unresolved: list[str] = []
    targets: list[dict[str, Any]] = []
    risks: list[str] = []

    wanted = {k for k in (kinds_filter or []) if k in VALID_KINDS} or None

    for pf in parsed_files:
        unresolved.extend(pf.get("unresolvedSymbols", []))
        imports = pf.get("imports", [])
        for cls in pf.get("classes", []):
            fqcn = cls.get("fqcn", "")
            kind = cls.get("kind", "unknown")
            if kind not in VALID_KINDS:
                kind = "unknown"
            if wanted is not None and kind not in wanted:
                continue
            nodes.append(fqcn)
            # Dependency edges from injected field types (collaborators).
            for field in cls.get("fields", []):
                ftype = _short(field.get("type", ""))
                if ftype and ftype[:1].isupper():
                    edges.append({"from": fqcn, "to": ftype, "via": "field"})
            for imp in imports:
                if imp.endswith("*"):
                    continue
            targets.append(
                {
                    "fqcn": fqcn,
                    "kind": kind,
                    "publicMethods": _public_methods(cls),
                    "annotations": cls.get("annotations", []),
                    "stereotype": next(
                        (a for a in cls.get("annotations", []) if a in SPRING_STEREOTYPES),
                        None,
                    ),
                }
            )
            risks.extend(_risk_points_for(cls))

    result["testTargets"] = targets
    result["dependencyGraph"] = {"nodes": sorted(set(nodes)), "edges": edges}
    result["unresolvedSymbols"] = sorted(set(unresolved))
    result["riskPoints"] = sorted(set(risks))
    result["evidence"] = [pf["file"] for pf in parsed_files]

    if denied:
        result["warnings"].append(
            f"{len(denied)} path(s) outside REPO_AST_ALLOW_ROOT or missing were skipped"
        )

    stereotype_count = sum(1 for t in targets if t.get("stereotype"))
    result["summary"] = (
        f"Parsed {len(parsed_files)} file(s) [mode={parse_mode}]: "
        f"{len(targets)} target(s), {stereotype_count} Spring stereotype(s), "
        f"{len(result['unresolvedSymbols'])} unresolved symbol(s)."
    )

    if not parsed_files and not denied:
        result["status"] = "failed"
        result["errors"].append("No Java files found for the requested paths.")
        result["nextActions"].append("Verify the paths point at .java files inside REPO_AST_ALLOW_ROOT.")
    elif degraded or result["unresolvedSymbols"] or denied:
        result["status"] = "partial"
        if degraded:
            result["nextActions"].append(
                "Build the JavaParser CLI jar (mcp/javaparser-cli) and/or set "
                "REPO_AST_JAVAPARSER_JAR for full symbol resolution."
            )
        if result["unresolvedSymbols"]:
            result["nextActions"].append(
                "Augment with the JDT LS LSP to resolve remaining symbols."
            )
    else:
        result["status"] = "ok"

    return result


def _analyze(paths: list[str], kinds: Optional[list[str]] = None) -> dict[str, Any]:
    """Core analysis entrypoint shared by every tool. Pure / side-effect free."""
    root = _allow_root()
    files, denied = _collect_java_files(paths, root)

    jar = _locate_jar()
    use_java = bool(jar) and _jdk_available()
    parsed: list[dict[str, Any]] = []
    degraded = not use_java

    if not files:
        return _build_result(
            [], degraded=degraded, denied=denied, kinds_filter=kinds, parse_mode="none"
        )

    if use_java and jar is not None:
        for f in files:
            data = _run_java_cli(jar, f)
            if data is None:
                # Fall back per-file so one bad file doesn't abort everything.
                degraded = True
                parsed.append(_fallback_parse_file(f))
            else:
                parsed.append(_normalize_java_cli_output(data, f))
    else:
        for f in files:
            parsed.append(_fallback_parse_file(f))

    parse_mode = "javaparser" if (use_java and not degraded) else "regex-fallback"
    return _build_result(
        parsed, degraded=degraded, denied=denied, kinds_filter=kinds, parse_mode=parse_mode
    )


def _normalize_java_cli_output(data: dict[str, Any], path: Path) -> dict[str, Any]:
    """Coerce the Java CLI JSON into the internal parsed-file shape.

    The Java CLI emits classes with annotations; ensure each class carries a
    ``kind`` derived from its stereotypes so downstream assembly is uniform.
    Method bodies are never present in the CLI output by contract.
    """
    package = data.get("package", "")
    classes = data.get("classes", []) or []
    for cls in classes:
        # Normalize annotations to bare simple names (e.g. "@RestController" ->
        # "RestController") so they match SPRING_STEREOTYPES keys, matching the
        # regex-fallback shape produced by _annotations_from.
        annos = [_short(str(a).lstrip("@")) for a in cls.get("annotations", [])]
        cls["annotations"] = annos
        name = cls.get("name", "")
        if not cls.get("fqcn"):
            cls["fqcn"] = f"{package}.{name}" if package else name
        if not cls.get("kind"):
            cls["kind"] = _classify_kind(annos, cls.get("extendsImplements", ""))
        # Defensive: strip any body field a CLI might have included.
        for m in cls.get("methods", []):
            m.pop("body", None)
    return {
        "file": str(path),
        "package": package,
        "imports": data.get("imports", []),
        "classes": classes,
        "unresolvedSymbols": data.get("unresolvedSymbols", []),
    }


# ---------------------------------------------------------------------------
# MCP server wiring
# ---------------------------------------------------------------------------


def build_server() -> Any:
    """Construct and return the configured FastMCP server.

    Kept as a function so the module imports cleanly even when the ``mcp``
    package is absent (e.g. under ``py_compile`` or unit tests of the pure
    analysis functions).
    """
    if FastMCP is None:  # pragma: no cover
        raise RuntimeError(
            "The 'mcp' package is not installed. Install with: pip install 'mcp[cli]'"
        )

    mcp = FastMCP(SERVER_NAME)

    @mcp.tool()
    def parse_java_file(path: str) -> dict:
        """Parse a single Java file, returning structure-only AST metadata.

        Emits class/method signatures, fields and annotations (never method
        bodies). Conforms to AstAnalysisResult.
        """
        return _analyze([path])

    @mcp.tool()
    def resolve_symbol(paths: list[str], symbol: str) -> dict:
        """Locate a fully-qualified type or simple name across the given paths.

        Returns an AstAnalysisResult whose testTargets are filtered to types
        whose FQCN or simple name matches ``symbol``; unmatched references are
        reported in ``unresolvedSymbols``.
        """
        full = _analyze(paths)
        needle = symbol.strip()
        matched = [
            t
            for t in full["testTargets"]
            if t["fqcn"] == needle or _short(t["fqcn"]) == _short(needle)
        ]
        full["testTargets"] = matched
        if not matched:
            full["unresolvedSymbols"] = sorted(set(full["unresolvedSymbols"] + [needle]))
            full["status"] = "partial"
            full["summary"] = f"Symbol '{symbol}' not resolved among scanned files."
            full["nextActions"].append(
                "Widen the path scope or build the JavaParser jar for full resolution."
            )
        else:
            full["summary"] = f"Resolved '{symbol}' to {len(matched)} type(s)."
        return full

    @mcp.tool()
    def list_spring_components(paths: list[str]) -> dict:
        """List Spring stereotype components found under the given paths.

        Detects @RestController/@Controller/@Service/@Repository/@Component and
        classifies each into a target kind.
        """
        return _analyze(paths, kinds=["controller", "service", "repository", "component"])

    @mcp.tool()
    def extract_test_targets(paths: list[str], kinds: list[str] | None = None) -> dict:
        """Extract test-target candidates (public methods + Spring stereotypes).

        ``kinds`` optionally restricts results to a subset of
        controller/service/repository/component/pojo/unknown. Output conforms to
        AstAnalysisResult. Symbols are never inferred: unresolved references are
        returned in ``unresolvedSymbols``. Method bodies are never returned.
        """
        return _analyze(paths, kinds=kinds)

    @mcp.resource("ast://index")
    def ast_index() -> str:
        """Return a JSON index of test targets discovered under the allow root."""
        root = _allow_root() or Path.cwd()
        result = _analyze([str(root)])
        index = {
            "root": str(root),
            "degraded": result["degraded"],
            "targets": [
                {"fqcn": t["fqcn"], "kind": t["kind"], "stereotype": t.get("stereotype")}
                for t in result["testTargets"]
            ],
            "unresolvedSymbols": result["unresolvedSymbols"],
        }
        return json.dumps(index, indent=2)

    @mcp.resource("ast://dependency-graph")
    def ast_dependency_graph() -> str:
        """Return the collaborator dependency graph as JSON (nodes + edges)."""
        root = _allow_root() or Path.cwd()
        result = _analyze([str(root)])
        return json.dumps(result["dependencyGraph"], indent=2)

    @mcp.prompt()
    def explain_target_shape(fqcn: str) -> str:
        """Prompt template: explain a target's testable shape for harnessing."""
        return (
            f"Using only structure-only AST metadata for `{fqcn}` (never source "
            "bodies), explain its testable shape for a Spring test harness:\n"
            "1. Classify the Spring stereotype/kind (controller/service/"
            "repository/component/pojo) and the recommended test slice "
            "(@WebMvcTest+MockMvc, @DataJpaTest, or a plain unit test).\n"
            "2. List public methods that are test targets and the collaborators "
            "(injected fields) that should be mocked with @MockitoBean.\n"
            "3. Call out test seams / risk points (clock, randomness, external "
            "I/O, filesystem) that need deterministic substitution.\n"
            "4. Note any unresolved symbols that reduce confidence.\n"
            "Do not invent members that are not present in the AST metadata."
        )

    return mcp


def main() -> None:
    """Entry point: run the server over stdio."""
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
