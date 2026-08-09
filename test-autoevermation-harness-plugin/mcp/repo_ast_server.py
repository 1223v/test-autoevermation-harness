#!/usr/bin/env python3
"""repo-ast MCP server.

A FastMCP (official MCP Python SDK) server that performs *structure-only* Java
AST/symbol analysis for the Spring test-harness plugin.

Design contract (see RESEARCH_NOTES.md sections 1-2):

* High-level API: ``from mcp.server.fastmcp import FastMCP`` with ``@mcp.tool()``
  decorators ONLY; stdio transport. v0.33.0 deleted the ``ast://index`` /
  ``ast://dependency-graph`` resources and the ``explain_target_shape`` prompt — they were
  FastMCP boilerplate (RESEARCH_NOTES §1; ``ast_index``/``explain_target_shape`` were the
  SDK example's own names) that no agent could reach, duplicated ``extract_test_targets``,
  and — unlike the tools — took no ``paths`` argument, so each read ran ``_analyze()`` over
  the ENTIRE allow root. The prompt had also drifted: it prescribed ``@MockitoBean``
  unconditionally although this harness branches to ``@MockBean`` for Boot ≤3.3
  (version-compatibility.md §2-B/2-C). Do not re-add resources/prompts here.
* Java AST is produced by a bundled JavaParser symbol-solver CLI jar invoked via
  ``subprocess`` returning JSON. It is the ONLY backend: a missing jar or JDK is
  always a hard failure (``JAVAPARSER_REQUIRED``, fallback-policy.md #2).
  v0.31.0 deleted the pure-Python regex extractor that used to serve standalone
  use, so ``REPO_AST_REQUIRE_JAVAPARSER`` is now a no-op retained only for config
  compatibility. A file JavaParser cannot parse is skipped, sets
  ``degraded: true`` and is named in ``warnings`` — never approximated.
* Output conforms to the ``AstAnalysisResult`` schema:
  ``status``/``summary``/``testTargets[]``/``dependencyGraph``/
  ``unresolvedSymbols[]``/``riskPoints[]``/``evidence``/``warnings``/``errors``/
  ``nextActions``.
* SECURITY: never returns method *bodies* or call *arguments* (only signatures /
  annotations / metadata; invoked method *names* are exposed as structure
  metadata for the scenario target-call conformance gate); enforces a path
  allowlist rooted at ``REPO_AST_ALLOW_ROOT``; performs no network access.

The module is import-safe: importing it (or running ``py_compile``) must not
require the ``mcp`` package to be installed. Analysis, however, always requires
the JavaParser jar + a JDK — build it with setup-harness E6.
"""

from __future__ import annotations

import functools
import glob
import hashlib
import json
import os
import re
import subprocess
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

#: Built-in Spring MVC/WebFlux request-mapping annotations. A custom annotation
#: meta-annotated (transitively) with any of these is a "composed mapping" whose
#: URL path/HTTP method live on @AliasFor overrides and are not visible on the
#: bare annotation name -- the generator must confirm them before building a
#: MockMvc request. See Spring ref "Composed @RequestMapping Variants".
REQUEST_MAPPING_ANNOTATIONS = frozenset(
    {
        "RequestMapping",
        "GetMapping",
        "PostMapping",
        "PutMapping",
        "DeleteMapping",
        "PatchMapping",
    }
)

#: Specialization order: when a custom stereotype is meta-annotated with several
#: stereotypes, the most specific kind wins (Spring treats @Service etc. as
#: specializations of @Component).
_STEREOTYPE_PRIORITY = ("controller", "repository", "service", "component")


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


def _data_dir() -> Path:
    """Durable per-plugin data directory (mirrors bootstrap.py data_dir()).

    ``CLAUDE_PLUGIN_DATA`` survives plugin updates; the version-keyed plugin
    cache directory (``CLAUDE_PLUGIN_ROOT``) does not — official docs say not to
    store state there. Local-dev fallback: ``mcp/.plugin-data``.
    """
    env = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / ".plugin-data"


#: Durable jar location + source fingerprint marker (written by
#: scripts/persist_astcli_jar.py after an E6 build; see setup-harness).
_DATA_JAR_SUBDIR = "javaparser"
_FINGERPRINT_BASENAME = "astcli.fingerprint"


def _source_fingerprint() -> Optional[str]:
    """16-hex sha256 fingerprint of the bundled javaparser-cli sources.

    Covers ``pom.xml`` + every ``src/**/*.java`` (relative path + bytes), so a
    CLI source change between plugin versions invalidates a persisted jar.
    Canonical twin: scripts/persist_astcli_jar.py source_fingerprint() —
    tests/test_update_persistence.py asserts both stay identical. Never raises.
    """
    try:
        cli_dir = Path(__file__).resolve().parent / "javaparser-cli"
        h = hashlib.sha256()
        pom = cli_dir / "pom.xml"
        if not pom.is_file():
            return None
        h.update(b"pom.xml\0")
        h.update(pom.read_bytes())
        for java in sorted(cli_dir.glob("src/**/*.java")):
            h.update(str(java.relative_to(cli_dir)).replace("\\", "/").encode())
            h.update(b"\0")
            h.update(java.read_bytes())
        return h.hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def _match_jar(directory: Path) -> Optional[str]:
    """Newest-preferred jar match in ``directory`` (shaded first), or None."""
    patterns = ["*-shaded.jar", "*-jar-with-dependencies.jar", "*.jar"]
    for pattern in patterns:
        matches = sorted(glob.glob(str(directory / pattern)))
        # Skip the thin "original-" artifacts produced by the shade plugin.
        matches = [m for m in matches if not Path(m).name.startswith("original-")]
        if matches:
            return matches[0]
    return None


def _locate_jar() -> Optional[str]:
    """Locate the JavaParser CLI shaded jar.

    Resolution order:
    1. ``REPO_AST_JAVAPARSER_JAR`` env var (explicit path).
    2. ``mcp/javaparser-cli/target/*.jar`` relative to this file — a fresh
       local build always wins (dev iteration).
    3. ``${CLAUDE_PLUGIN_DATA}/javaparser/*.jar`` — the durable copy that
       survives plugin updates (the version-keyed cache snapshot ships no jar
       because ``target/`` is gitignored; without this candidate every update
       destroyed the jar and hard-failed repo-ast under
       REPO_AST_REQUIRE_JAVAPARSER=1).
    """
    env_jar = os.environ.get("REPO_AST_JAVAPARSER_JAR", "").strip()
    if env_jar and Path(env_jar).is_file():
        return env_jar

    jar = _match_jar(_target_dir())
    if jar:
        return jar
    return _match_jar(_data_dir() / _DATA_JAR_SUBDIR)


def _target_dir() -> Path:
    """Local Maven build output dir (fresh dev builds; empty in cache snapshots)."""
    return Path(__file__).resolve().parent / "javaparser-cli" / "target"


@functools.lru_cache(maxsize=1)
def _jdk_available() -> bool:
    """Return True when a ``java`` runtime can be invoked.

    Memoized: JDK availability (and ``REPO_AST_JAVA_BIN``) is fixed for a process,
    so the probe runs at most once even when the failure path re-checks it.
    """
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


def _require_javaparser() -> bool:
    """Strict mode: when truthy, the JavaParser jar + JDK are REQUIRED and the
    pure-Python regex fallback is disabled (fallback-policy.md #2). Missing
    capability becomes a hard failure instead of a silent degrade."""
    val = os.environ.get("REPO_AST_REQUIRE_JAVAPARSER", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _plugin_version() -> Optional[str]:
    """Best-effort read of the plugin's declared version, or ``None`` on failure.

    Reads ``.claude-plugin/plugin.json`` next to the plugin root (this file lives
    in ``mcp/``). Never raises: any error degrades to ``None``.
    """
    try:
        manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except Exception:  # noqa: BLE001
        return None


def _run_java_cli(jar: str, target: Path) -> Optional[dict[str, Any]]:
    """Invoke the JavaParser CLI jar and parse its JSON output.

    Returns the parsed dict, or ``None`` on any failure (caller falls back to the
    pure-Python extractor). Never raises.
    """
    java = os.environ.get("REPO_AST_JAVA_BIN", "java")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed args, no shell
            [java, "-jar", jar, str(target)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
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
# Java source-text helpers (annotation meta-index; shared by the JavaParser
# normalizer). v0.31.0 deleted the regex extractor these once also served.
# ---------------------------------------------------------------------------

_ANNO_RE = re.compile(r"@([\w.]+)(?:\([^)]*\))?")
# Method signature: optional annotations, modifiers, return type, name, params.
# Annotation type declaration: ``@interface Name`` plus the annotations that
# precede it (its meta-annotations). Used to resolve custom stereotypes and
# composed mapping annotations across files.
_ANNO_DECL_RE = re.compile(
    r"(?P<annos>(?:@[\w.]+(?:\([^)]*\))?\s*)*?)"
    r"(?:public|protected|private|abstract|static|strictfp|\s)*"
    r"@interface\s+(?P<name>[A-Za-z_]\w*)"
)
# Field: modifiers, type, name (no method parens before ; ).
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


def _scan_annotation_decls(text: str) -> dict[str, list[str]]:
    """Map every ``@interface`` declared in ``text`` to its meta-annotations.

    Returns ``{AnnotationSimpleName: [meta-anno simple names]}``. Used to resolve
    custom stereotypes (``@UseCase`` -> ``@Component``) and composed mapping
    annotations (``@GetJson`` -> ``@RequestMapping``) across files. Comments and
    string literals must already be stripped by the caller.
    """
    decls: dict[str, list[str]] = {}
    for m in _ANNO_DECL_RE.finditer(text):
        name = m.group("name")
        metas = [a for a in _annotations_from(m.group("annos")) if a != "interface"]
        decls[name] = metas
    return decls


def _resolve_meta_to(
    name: str,
    decls: dict[str, list[str]],
    base: dict[str, str] | frozenset,
    _seen: set[str] | None = None,
) -> set[str]:
    """Transitively resolve ``name`` to the set of ``base`` keys it maps onto.

    ``base`` is either ``SPRING_STEREOTYPES`` (dict) for stereotype resolution or
    ``REQUEST_MAPPING_ANNOTATIONS`` (set) for composed-mapping resolution. Follows
    meta-annotations to arbitrary depth (Spring resolves stereotypes transitively)
    with a cycle guard.
    """
    _seen = _seen or set()
    if name in _seen:
        return set()
    _seen.add(name)
    hits: set[str] = set()
    if name in base:
        hits.add(name)
    for meta in decls.get(name, []):
        if meta in base:
            hits.add(meta)
        if meta in decls:  # custom annotation -> recurse for transitive depth
            hits |= _resolve_meta_to(meta, decls, base, _seen)
    return hits


def _build_meta_index(decls: dict[str, list[str]]) -> tuple[dict[str, str], set[str]]:
    """Build ``(custom_stereotype_kind, composed_mapping_names)`` from decls.

    * ``custom_stereotype_kind``: custom annotation simple name -> coarse kind
      (controller/service/repository/component), most-specific stereotype wins.
    * ``composed_mapping_names``: custom annotations that are (transitively)
      meta-annotated with a Spring request-mapping annotation.
    """
    stereotypes: dict[str, str] = {}
    mappings: set[str] = set()
    for name in decls:
        stereo_hits = _resolve_meta_to(name, decls, SPRING_STEREOTYPES)
        kinds = {SPRING_STEREOTYPES[h] for h in stereo_hits}
        for kind in _STEREOTYPE_PRIORITY:
            if kind in kinds:
                stereotypes[name] = kind
                break
        if _resolve_meta_to(name, decls, REQUEST_MAPPING_ANNOTATIONS):
            mappings.add(name)
    return stereotypes, mappings


def _classify_kind(
    annotations: list[str],
    implements_blob: str,
    custom_stereotypes: dict[str, str] | None = None,
) -> str:
    for anno in annotations:
        if anno in SPRING_STEREOTYPES:
            return SPRING_STEREOTYPES[anno]
    if custom_stereotypes:
        for anno in annotations:
            if anno in custom_stereotypes:
                return custom_stereotypes[anno]
    for hint in JPA_REPOSITORY_HINTS:
        if hint in implements_blob:
            return "repository"
    return "pojo"


#: Tokens that can appear where ``_FIELD_RE`` expects a field *type* but are not
#: real fields — control-flow keywords and (in the collapsed member skeleton)
#: the leading keyword of a nested type declaration header.
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


def _failed_result(code: str, message: str, remediation: list[str]) -> dict[str, Any]:
    """Build a hard-failure AstAnalysisResult (used by strict capability gates)."""
    result = _empty_result()
    result["status"] = "failed"
    result["degraded"] = True
    result["summary"] = message
    result["errors"] = [{"code": code, "message": message}]
    result["nextActions"] = remediation
    return result


def _public_methods(cls: dict[str, Any]) -> list[str]:
    return [m["signature"] for m in cls.get("methods", []) if m.get("signature")]


def _method_calls(cls: dict[str, Any]) -> dict[str, list[str]]:
    """Map each method name to the simple names of methods its body invokes.

    Names only — never arguments or bodies. Empty lists under the regex
    fallback (only the JavaParser CLI extracts call expressions). Used by the
    scenario target-call conformance gate (test-code-generator Stage 5 /
    scenario-conformance-verifier Stage 9)."""
    return {
        m["name"]: list(m.get("invokedMethods") or [])
        for m in cls.get("methods", [])
        if m.get("name")
    }


def _method_call_details(cls: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Map each method name to its receiver-aware call records
    ({"name", "scope"}), where scope is the bare receiver identifier
    ("orderService", "this") or "" when the receiver was complex or absent.
    Lets the conformance gate distinguish same-named methods on different
    collaborators (orderService.cancel() vs paymentClient.cancel()) by joining
    scope against the test class's field types. Empty under the regex fallback
    (only the JavaParser CLI extracts call expressions)."""
    return {
        m["name"]: [
            {"name": str(c.get("name", "")), "scope": str(c.get("scope", ""))}
            for c in (m.get("invokedCalls") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        for m in cls.get("methods", [])
        if m.get("name")
    }


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


def _composed_mapping_risks(
    cls: dict[str, Any], composed_mappings: set[str]
) -> list[str]:
    """Flag controller endpoints whose HTTP path/verb hide behind a composed
    ``@RequestMapping`` variant, so the generator confirms them instead of
    guessing. The path lives on an ``@AliasFor`` override, invisible to AST."""
    if not composed_mappings or cls.get("kind") != "controller":
        return []
    fqcn = cls.get("fqcn", "?")
    risks: list[str] = []
    cls_hits = sorted(set(cls.get("annotations", [])) & composed_mappings)
    for anno in cls_hits:
        risks.append(
            f"{fqcn}: class-level composed mapping @{anno} detected; confirm base "
            f"path/HTTP method (@AliasFor override) before building MockMvc requests"
        )
    for m in cls.get("methods", []):
        hits = sorted(set(m.get("annotations", [])) & composed_mappings)
        for anno in hits:
            risks.append(
                f"{fqcn}#{m.get('name', '?')}: composed mapping @{anno} detected; "
                f"confirm URL path/HTTP method (@AliasFor override) before building "
                f"the MockMvc request"
            )
    return risks


def _build_result(
    parsed_files: list[dict[str, Any]],
    *,
    degraded: bool,
    denied: list[str],
    kinds_filter: Optional[list[str]],
    parse_mode: str,
    custom_stereotypes: dict[str, str] | None = None,
    composed_mappings: set[str] | None = None,
) -> dict[str, Any]:
    result = _empty_result()
    result["degraded"] = degraded
    custom_stereotypes = custom_stereotypes or {}
    composed_mappings = composed_mappings or set()

    nodes: list[str] = []
    edges: list[dict[str, str]] = []
    unresolved: list[str] = []
    targets: list[dict[str, Any]] = []
    risks: list[str] = []

    wanted = {k for k in (kinds_filter or []) if k in VALID_KINDS} or None

    for pf in parsed_files:
        unresolved.extend(pf.get("unresolvedSymbols", []))
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
            targets.append(
                {
                    "fqcn": fqcn,
                    "kind": kind,
                    "publicMethods": _public_methods(cls),
                    "methodCalls": _method_calls(cls),
                    "methodCallDetails": _method_call_details(cls),
                    "annotations": cls.get("annotations", []),
                    "stereotype": next(
                        (
                            a
                            for a in cls.get("annotations", [])
                            if a in SPRING_STEREOTYPES or a in custom_stereotypes
                        ),
                        None,
                    ),
                }
            )
            risks.extend(_risk_points_for(cls))
            risks.extend(_composed_mapping_risks(cls, composed_mappings))

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
                "Run /test-autoevermation-harness-plugin:setup-harness (E6) to build+persist "
                "the JavaParser CLI jar, and/or set REPO_AST_JAVAPARSER_JAR for full symbol resolution."
            )
        if result["unresolvedSymbols"]:
            result["nextActions"].append(
                "Narrow `targets`/add the defining sources so remaining symbols "
                "resolve, or rely on the pipeline's JDT LS stage (analyze-source) "
                "for semantic augmentation — this server itself has no LSP backend."
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
    degraded = False

    # JavaParser is the only backend (fallback-policy.md #2). v0.31.0 deleted the
    # regex extractor, so a missing jar/JDK is always a hard failure — previously
    # this depended on REPO_AST_REQUIRE_JAVAPARSER, which .mcp.json pinned to "1"
    # anyway. The env var is now a no-op kept for config compatibility.
    if not use_java:
        return _failed_result(
            "JAVAPARSER_REQUIRED",
            "JavaParser jar/JDK is required but unavailable "
            f"(jar={'found' if jar else 'missing'}, "
            f"jdk={'ok' if _jdk_available() else 'missing'}).",
            [
                "Run /test-autoevermation-harness-plugin:setup-harness (E6: \"${CLAUDE_PLUGIN_ROOT}\"/mcp/javaparser-cli 빌드 후 "
                "CLAUDE_PLUGIN_DATA로 persist), or set REPO_AST_JAVAPARSER_JAR to a prebuilt astcli shaded jar.",
                "Ensure a JDK 'java' runtime is on PATH (or set REPO_AST_JAVA_BIN).",
            ],
        )

    if not files:
        return _build_result(
            [], degraded=degraded, denied=denied, kinds_filter=kinds, parse_mode="none"
        )

    # Pass 1: scan every file for @interface declarations and resolve custom
    # stereotypes / composed mapping annotations transitively across the whole
    # file set. This must precede classification because a custom stereotype
    # (e.g. @UseCase) is usually declared in a different file from where it is
    # used, and neither extractor backend surfaces meta-annotations on its own.
    decls: dict[str, list[str]] = {}
    for f in files:
        try:
            cleaned = _strip_comments_and_strings(
                f.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue
        decls.update(_scan_annotation_decls(cleaned))
    custom_stereotypes, composed_mappings = _build_meta_index(decls)

    # Pass 2: parse + classify with the resolved meta index. A file JavaParser
    # cannot read is skipped and flagged, not silently approximated: v0.31.0
    # removed the per-file regex fallback, and dropping to a heuristic parse would
    # emit an incomplete symbol set that reads as authoritative. Skipping one file
    # is preferable to failing the whole run over a single unparseable source.
    java_parsed = 0
    unparsed: list[str] = []
    for f in files:
        data = _run_java_cli(jar, f)
        if data is None:
            degraded = True
            unparsed.append(str(f))
            continue
        java_parsed += 1
        parsed.append(_normalize_java_cli_output(data, f, custom_stereotypes))

    result = _build_result(
        parsed,
        degraded=degraded,
        denied=denied,
        kinds_filter=kinds,
        parse_mode="javaparser" if java_parsed else "none",
        custom_stereotypes=custom_stereotypes,
        composed_mappings=composed_mappings,
    )
    if unparsed:
        # degraded:true is a hard-stop signal for consumers (fallback-policy #2),
        # so name the offending files instead of leaving the flag unexplained.
        result["warnings"].append(
            "JavaParser could not parse %d file(s); they are absent from this "
            "result: %s" % (len(unparsed), ", ".join(sorted(unparsed)[:10]))
        )
    return result


def _normalize_java_cli_output(
    data: dict[str, Any], path: Path, custom_stereotypes: dict[str, str] | None = None
) -> dict[str, Any]:
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
        # shape produced by _annotations_from.
        annos = [_short(str(a).lstrip("@")) for a in cls.get("annotations", [])]
        cls["annotations"] = annos
        name = cls.get("name", "")
        # Package is per-compilation-unit: prefer the class's own package (emitted
        # when the CLI parsed a multi-file directory) and fall back to the top-level
        # package for single-file payloads. Popped so the internal key never leaks
        # into the output — identical result for the single-file harness path.
        pkg = cls.pop("package", "") or package
        if not cls.get("fqcn"):
            cls["fqcn"] = f"{pkg}.{name}" if pkg else name
        # Always (re)classify with the cross-file custom-stereotype map so a
        # class annotated with a meta-annotated custom stereotype (e.g. @UseCase)
        # is not left as a bare pojo. The CLI never emits @interface declarations,
        # so this map is the only source of meta-annotation knowledge.
        cli_kind = cls.get("kind")
        if not cli_kind or cli_kind == "pojo":
            cls["kind"] = _classify_kind(
                annos, cls.get("extendsImplements", ""), custom_stereotypes
            )
        # Defensive: strip any body field a CLI might have included; keep the
        # invoked-method *names* (structure metadata, no arguments/bodies).
        for m in cls.get("methods", []):
            m.pop("body", None)
            m["invokedMethods"] = [str(c) for c in (m.get("invokedMethods") or [])]
            m["invokedCalls"] = [
                {"name": str(c.get("name", "")), "scope": str(c.get("scope", ""))}
                for c in (m.get("invokedCalls") or [])
                if isinstance(c, dict) and c.get("name")
            ]
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
            "The 'mcp' package is not installed for this interpreter. Install with: "
            "python3 -m pip install -r mcp/requirements.txt"
        )

    mcp = FastMCP(SERVER_NAME)

    @mcp.tool()
    def health() -> dict:
        """Side-effect-free diagnostic probe: report server capability status.

        Reports whether the JavaParser jar/JDK are available and the strict-mode
        flag, without parsing anything. This is a probe, NOT a capability gate: it
        never hard-fails when the jar is missing even under
        REPO_AST_REQUIRE_JAVAPARSER=1, and every field degrades to None/False on
        error rather than raising.
        """
        jar_path: Optional[str] = None
        java_ok = False
        require = False
        allow_root: Optional[str] = None
        try:
            jar_path = _locate_jar()
        except Exception:  # noqa: BLE001
            jar_path = None
        try:
            java_ok = _jdk_available()
        except Exception:  # noqa: BLE001
            java_ok = False
        try:
            require = _require_javaparser()
        except Exception:  # noqa: BLE001
            require = False
        try:
            root = _allow_root()
            allow_root = str(root) if root is not None else None
        except Exception:  # noqa: BLE001
            allow_root = None
        jar_persisted: Optional[bool] = None
        jar_stale: Optional[bool] = None
        try:
            data_jar_dir = _data_dir() / _DATA_JAR_SUBDIR
            if jar_path is not None:
                jar_persisted = Path(jar_path).resolve().parent == data_jar_dir.resolve()
            marker = data_jar_dir / _FINGERPRINT_BASENAME
            if _match_jar(data_jar_dir) and marker.is_file():
                recorded = marker.read_text(encoding="utf-8").strip()
                current = _source_fingerprint()
                if recorded and current:
                    jar_stale = recorded != current
        except Exception:  # noqa: BLE001
            jar_persisted, jar_stale = None, None
        return {
            "server": "repo-ast",
            "pluginVersion": _plugin_version(),
            "javaparser": {
                "jarFound": jar_path is not None,
                "jarPath": jar_path,
                "javaOk": java_ok,
                "requireJavaparser": require,
                # 업데이트 생존성 진단: persisted=false는 jar가 버전 키 캐시에만
                # 있어 다음 플러그인 업데이트 때 소실됨을 뜻한다(E6 persist 필요).
                # stale=true는 CLI 소스가 바뀌어 재빌드가 필요함을 뜻한다.
                "jarPersisted": jar_persisted,
                "jarStale": jar_stale,
            },
            "allowRoot": allow_root,
        }

    @mcp.tool()
    def parse_java_file(path: str) -> dict:
        """Parse a single Java file, returning structure-only AST metadata.

        Emits class/method signatures, fields and annotations (never method
        bodies or call arguments). Each testTarget additionally carries
        ``methodCalls`` — a map of method name to the simple names of methods
        invoked inside it — used to verify
        that a generated test's ``// when`` actually calls the scenario's
        ``target`` method, and ``methodCallDetails`` — the receiver-aware form
        ({"name", "scope"}) where scope is the bare receiver identifier or ""
        when complex/absent. Join scope against the class's ``fields`` types to
        distinguish same-named methods on different collaborators. Conforms to
        AstAnalysisResult.
        """
        return _analyze([path])

    @mcp.tool()
    def resolve_symbol(paths: list[str], symbol: str) -> dict:
        """Locate a fully-qualified type or simple name across the given paths.

        Returns an AstAnalysisResult whose testTargets are filtered to types
        whose FQCN or simple name matches ``symbol``; unmatched references are
        reported in ``unresolvedSymbols``.

        SCOPE NOTE: only ``testTargets`` is filtered to the match —
        ``dependencyGraph``/``riskPoints``/``unresolvedSymbols``/``evidence``
        remain scoped to the ENTIRE analyzed path set. Narrow ``paths`` if you
        need those fields scoped to the symbol as well.
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

    return mcp


def main() -> None:
    """Entry point: run the server over stdio."""
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
