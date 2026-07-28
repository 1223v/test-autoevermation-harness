"""Plugin-update persistence contract tests (v0.28.0).

Background (official docs, 2026-07 audit): the installed plugin lives in a
version-keyed cache snapshot (``~/.claude/plugins/cache/<mkt>/<plugin>/<ver>/``)
that is replaced on every update and garbage-collected after 14 days —
"treat CLAUDE_PLUGIN_ROOT as ephemeral and don't write state there". Only
``CLAUDE_PLUGIN_DATA`` survives updates. These tests pin the fixes:

  1. The astcli jar resolves from the durable data dir when the cache
     snapshot ships none (target/ is gitignored → every update used to
     destroy the jar and hard-fail repo-ast under REQUIRE_JAVAPARSER=1).
  2. persist_astcli_jar.py and repo_ast_server compute the SAME source
     fingerprint (stale-jar detection stays coherent).
  3. bootstrap's venv marker folds in the plugin version, so an update
     forces one dependency re-verification.
  4. Runtime docs anchor the E6 build to ${CLAUDE_PLUGIN_ROOT} (setup-harness
     runs with cwd = target project, where a bare relative cd breaks) and the
     update/cleanup guides cover reload + all data-dir variants.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repo_ast = _load_module("up_repo_ast_server", PLUGIN_ROOT / "mcp" / "repo_ast_server.py")

JAR = PLUGIN_ROOT / "mcp" / "javaparser-cli" / "target" / "astcli-1.0.0-shaded.jar"
EXAMPLES_JAVA = PLUGIN_ROOT / "examples" / "java"
persist = _load_module("up_persist_astcli_jar", PLUGIN_ROOT / "scripts" / "persist_astcli_jar.py")
bootstrap = _load_module("up_bootstrap", PLUGIN_ROOT / "mcp" / "bootstrap.py")


class JarResolutionTests(unittest.TestCase):
    """#1 — durable data-dir candidate keeps the jar alive across updates."""

    def test_env_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "custom.jar"
            jar.write_bytes(b"x")
            with mock.patch.dict("os.environ", {"REPO_AST_JAVAPARSER_JAR": str(jar)}):
                self.assertEqual(str(jar), repo_ast._locate_jar())

    def test_fresh_target_build_beats_data_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            data = Path(tmp) / "data" / "javaparser"
            target.mkdir(parents=True)
            data.mkdir(parents=True)
            (target / "astcli-2.0.0-shaded.jar").write_bytes(b"new")
            (data / "astcli-1.0.0-shaded.jar").write_bytes(b"old")
            with mock.patch.dict(
                "os.environ",
                {"CLAUDE_PLUGIN_DATA": str(Path(tmp) / "data"), "REPO_AST_JAVAPARSER_JAR": ""},
            ), mock.patch.object(repo_ast, "_target_dir", return_value=target):
                located = repo_ast._locate_jar()
        self.assertIsNotNone(located)
        self.assertEqual("astcli-2.0.0-shaded.jar", Path(located).name)

    def test_data_copy_serves_after_update_wipes_target(self) -> None:
        """Post-update state: cache snapshot has no target jar → durable copy used."""
        with tempfile.TemporaryDirectory() as tmp:
            empty_target = Path(tmp) / "target"
            empty_target.mkdir()
            data = Path(tmp) / "data" / "javaparser"
            data.mkdir(parents=True)
            (data / "astcli-1.0.0-shaded.jar").write_bytes(b"survivor")
            with mock.patch.dict(
                "os.environ",
                {"CLAUDE_PLUGIN_DATA": str(Path(tmp) / "data"), "REPO_AST_JAVAPARSER_JAR": ""},
            ), mock.patch.object(repo_ast, "_target_dir", return_value=empty_target):
                located = repo_ast._locate_jar()
        self.assertIsNotNone(located)
        self.assertEqual("astcli-1.0.0-shaded.jar", Path(located).name)

    def test_match_jar_prefers_shaded_and_skips_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "astcli-1.0.0.jar").write_bytes(b"thin")
            (d / "original-astcli-1.0.0-shaded.jar").write_bytes(b"pre-shade")
            (d / "astcli-1.0.0-shaded.jar").write_bytes(b"fat")
            self.assertEqual(
                "astcli-1.0.0-shaded.jar", Path(repo_ast._match_jar(d)).name
            )


class RegexFallbackRemovalTests(unittest.TestCase):
    """v0.31.0: JavaParser is the only backend — no silent regex approximation.

    The regex extractor was unreachable in plugin deployments (.mcp.json pins
    REPO_AST_REQUIRE_JAVAPARSER=1) yet carried ~200 lines and implied repo-ast
    could degrade to heuristics. These tests pin the two behaviours that replaced
    it, because both are easy to regress back into a silent fallback.
    """

    def test_regex_extractor_symbols_are_gone(self) -> None:
        for name in ("_fallback_parse_file", "_member_skeleton", "_type_body",
                     "_matching_brace_end", "_normalize_params", "_PACKAGE_RE",
                     "_METHOD_RE", "_FIELD_RE"):
            with self.subTest(symbol=name):
                self.assertFalse(hasattr(repo_ast, name), f"{name} came back")

    def test_missing_jar_hard_fails_even_without_the_require_env_var(self) -> None:
        """The env var is a no-op now; absence must never re-enable a fallback."""
        env = {"REPO_AST_ALLOW_ROOT": str(PLUGIN_ROOT)}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("REPO_AST_REQUIRE_JAVAPARSER", None)
            with mock.patch.object(repo_ast, "_locate_jar", lambda: None):
                result = repo_ast._analyze([str(EXAMPLES_JAVA)])
        self.assertEqual("failed", result["status"])
        self.assertEqual("JAVAPARSER_REQUIRED", result["errors"][0]["code"])

    def test_unparseable_file_is_skipped_and_named_not_approximated(self) -> None:
        """One bad file must not abort the run, nor be silently approximated."""
        if not JAR.exists():
            self.skipTest("astcli jar not built")
        real = repo_ast._run_java_cli
        seen = {"n": 0}

        def only_first_fails(jar, path):
            seen["n"] += 1
            return None if seen["n"] == 1 else real(jar, path)

        env = {"REPO_AST_ALLOW_ROOT": str(PLUGIN_ROOT)}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(repo_ast, "_run_java_cli", only_first_fails):
                result = repo_ast._analyze([str(EXAMPLES_JAVA)])

        self.assertTrue(result["degraded"], "skipped file must raise the stop signal")
        self.assertTrue(result["testTargets"], "other files must still be parsed")
        self.assertTrue(
            any("could not parse" in w for w in result["warnings"]),
            f"the skipped file must be named, got {result['warnings']}",
        )


class FingerprintTwinTests(unittest.TestCase):
    """#2 — server and persist script must agree on the source fingerprint."""

    def test_twins_agree_on_real_cli_sources(self) -> None:
        server_fp = repo_ast._source_fingerprint()
        script_fp = persist.source_fingerprint()
        self.assertIsNotNone(server_fp)
        self.assertEqual(server_fp, script_fp)

    def test_fingerprint_changes_when_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp)
            (cli / "pom.xml").write_text("<project/>", encoding="utf-8")
            src = cli / "src" / "main" / "java"
            src.mkdir(parents=True)
            (src / "A.java").write_text("class A {}", encoding="utf-8")
            before = persist.source_fingerprint(cli)
            (src / "A.java").write_text("class A { int x; }", encoding="utf-8")
            after = persist.source_fingerprint(cli)
        self.assertIsNotNone(before)
        self.assertNotEqual(before, after)

    @unittest.skipUnless(
        (PLUGIN_ROOT / "mcp" / "javaparser-cli" / "target").is_dir()
        and any((PLUGIN_ROOT / "mcp" / "javaparser-cli" / "target").glob("*-shaded.jar")),
        "astcli jar not built in this checkout",
    )
    def test_persist_roundtrip_reports_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"CLAUDE_PLUGIN_DATA": tmp}):
                self.assertFalse(persist.status()["upToDate"])
                result = persist.persist()
                self.assertEqual("ok", result["status"])
                self.assertTrue(persist.status()["upToDate"])
                marker = Path(tmp) / "javaparser" / "astcli.fingerprint"
                self.assertEqual(
                    repo_ast._source_fingerprint(),
                    marker.read_text(encoding="utf-8").strip(),
                )


class BootstrapVersionMarkerTests(unittest.TestCase):
    """#3 — a plugin version bump invalidates the venv marker once."""

    def test_marker_payload_contains_declared_plugin_version(self) -> None:
        import json

        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        payload = bootstrap.marker_payload()
        self.assertIsNotNone(payload)
        self.assertIn("# plugin-version: %s" % manifest["version"], payload)

    def test_old_version_marker_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "requirements.installed.txt"
            stale = bootstrap.marker_payload().replace(
                bootstrap.plugin_version(), "0.0.1"
            )
            marker.write_text(stale, encoding="utf-8")
            self.assertFalse(bootstrap.deps_ready(str(marker)))
            marker.write_text(bootstrap.marker_payload(), encoding="utf-8")
            self.assertTrue(bootstrap.deps_ready(str(marker)))


class DocContractTests(unittest.TestCase):
    """#4 — docs stay anchored and update guidance stays complete."""

    RUNTIME_DOCS = (
        "references/environment-setup.md",
        "references/fallback-policy.md",
        "skills/setup-harness/SKILL.md",
        "agents/ast-structure-analyzer.md",
    )

    def test_runtime_docs_have_no_cwd_relative_e6_build(self) -> None:
        for rel in self.RUNTIME_DOCS:
            text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "cd mcp/javaparser-cli", text,
                f"{rel}: E6 build must be ${{CLAUDE_PLUGIN_ROOT}}-anchored "
                "(setup-harness cwd is the target project)",
            )

    def test_e6_includes_persist_step_in_ssot_and_skill(self) -> None:
        for rel in ("references/environment-setup.md", "skills/setup-harness/SKILL.md",
                    "references/fallback-policy.md"):
            text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("persist_astcli_jar.py", text, rel)

    def test_update_guides_cover_reload_and_migration(self) -> None:
        for rel in ("README.md", "docs/GUIDE.md"):
            text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("/reload-plugins", text, rel)
            self.assertIn("setup-harness", text, rel)
            self.assertNotIn(
                "rm -rf ~/.claude/plugins/cache\n", text,
                f"{rel}: cache wipe must be scoped to this plugin's marketplace dir",
            )

    def test_cleanup_guide_lists_all_data_dir_variants(self) -> None:
        text = (PLUGIN_ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
        for variant in (
            "test-autoevermation-harness-plugin-test-autoevermation-harness",
            "test-autoevermation-harness-plugin-inline",
        ):
            self.assertIn(variant, text)


if __name__ == "__main__":
    unittest.main()
