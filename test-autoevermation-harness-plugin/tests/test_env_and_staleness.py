"""Environment-portability and evidence-freshness contract tests (v0.29.0).

Covers four changes that share one theme — the harness must not act on evidence or in
an environment it has not actually verified:

1. Security hooks removed (guard-read.py / guard-network.py). They fired outside any
   pipeline run and their protection target was already bounded by each agent's
   ``tools:`` allowlist. These tests keep them from silently returning.
2. bootstrap.py must not use os.execv on Windows — there exec* does not replace the
   process, so the MCP stdio chain dies at launch.
3. detect_pipeline_state must clamp the resume stage when durable evidence is older
   than the source it supposedly covers.
4. Multi-module JaCoCo reports must be aggregated, not sampled.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
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


build_test = _load_module("staleness_build_test_server",
                          PLUGIN_ROOT / "mcp" / "build_test_server.py")
bootstrap = _load_module("staleness_bootstrap", PLUGIN_ROOT / "mcp" / "bootstrap.py")
recorder = _load_module("staleness_record_run_context",
                        PLUGIN_ROOT / "scripts" / "record-run-context.py")


# --------------------------------------------------------------------- fixtures


def _write_jacoco(path: Path, *, missed: int, covered: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<report name="m">'
        f'<counter type="LINE" missed="{missed}" covered="{covered}"/>'
        f'<counter type="BRANCH" missed="{missed}" covered="{covered}"/>'
        f'<counter type="METHOD" missed="{missed}" covered="{covered}"/>'
        f'<counter type="CLASS" missed="{missed}" covered="{covered}"/>'
        f"</report>",
        encoding="utf-8",
    )


def _build_resumable_project(root: Path) -> None:
    """A project whose durable evidence would normally justify resuming at stage 9."""
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "main" / "java" / "OrderService.java").write_text(
        "class OrderService {}", encoding="utf-8")
    (root / "src" / "test" / "java").mkdir(parents=True)
    (root / "src" / "test" / "java" / "OrderServiceTest.java").write_text(
        "class OrderServiceTest {}", encoding="utf-8")
    (root / "test_docs").mkdir(parents=True)
    (root / "test_docs" / "INDEX.md").write_text("# Harness tests", encoding="utf-8")

    junit = root / "build" / "test-results" / "test" / "TEST-OrderServiceTest.xml"
    junit.parent.mkdir(parents=True)
    junit.write_text(
        '<testsuite name="OrderServiceTest" tests="1" failures="0">'
        '<testcase classname="OrderServiceTest" name="placesOrder"/></testsuite>',
        encoding="utf-8",
    )
    _write_jacoco(root / "build" / "reports" / "jacoco" / "test" / "jacocoTestReport.xml",
                  missed=0, covered=100)


def _touch_future(path: Path, seconds: int = 3600) -> None:
    """Make a file look edited well after everything else was written."""
    stamp = time.time() + seconds
    os.utime(path, (stamp, stamp))


# ------------------------------------------------------- 1. removed security hooks


class RemovedSecurityHooksTest(unittest.TestCase):
    """guard-read/guard-network are gone and must not come back unnoticed."""

    def test_guard_scripts_are_deleted(self) -> None:
        for name in ("guard-read.py", "guard-network.py"):
            self.assertFalse(
                (PLUGIN_ROOT / "scripts" / name).exists(),
                f"{name} was removed in v0.29.0: its protection target is already "
                "bounded by each agent's tools: allowlist, and it fired in sessions "
                "with no pipeline running",
            )

    def test_hooks_json_has_no_read_or_bash_matcher(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        matchers = [entry.get("matcher") for entry in hooks["hooks"]["PreToolUse"]]
        self.assertNotIn("Read|WebFetch", matchers)
        self.assertNotIn("Bash", matchers)

    def test_write_guard_is_registered_for_write_and_edit_only(self) -> None:
        """v0.32.0: the write guard is back, and it watches Write/Edit only.

        v0.30.0 unregistered it to stop false positives and v0.31.0 deleted it,
        which cost the #21 coverage invariant and the stage-ordering contract their
        only machine check. v0.32.0 restores it behind a run-active gate instead.
        """
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        guarded = [
            entry for entry in hooks["hooks"]["PreToolUse"]
            if "guard-gate-artifacts.py" in json.dumps(entry)
        ]
        self.assertEqual(1, len(guarded), "exactly one write guard registration")
        self.assertEqual("Write|Edit", guarded[0]["matcher"])
        self.assertTrue((PLUGIN_ROOT / "scripts" / "guard-gate-artifacts.py").exists())

    def test_write_guard_judges_nothing_outside_an_active_run(self) -> None:
        """The single gate that makes the guard tolerable — assert it in the source.

        Behavioural proof lives in tests/test_pipeline_v2.py
        (test_non_pipeline_session_is_never_blocked); this pins the structural
        invariant so the early-return cannot be refactored away silently.
        """
        source = (PLUGIN_ROOT / "scripts" / "guard-gate-artifacts.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("if not _run_active(workspace, session_id):", source)
        gate = source.index("if not _run_active(workspace, session_id):")
        for zone in ("_zone_a(", "_zone_b(", "_zone_c(", "MARKERS_DIR)"):
            with self.subTest(zone=zone):
                self.assertGreater(
                    source.rindex(zone), gate,
                    f"{zone} must be evaluated after the run-active gate",
                )

    def test_write_hooks_are_post_tool_use_and_warn_only(self) -> None:
        """Whatever still matches Write|Edit must run after the write, not gate it."""
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        write_entries = [
            entry for entry in hooks["hooks"]["PostToolUse"]
            if "Write" in (entry.get("matcher") or "")
        ]
        self.assertTrue(write_entries, "redact-secrets should still run post-write")
        for entry in write_entries:
            for hook in entry["hooks"]:
                with self.subTest(args=hook.get("args")):
                    self.assertIn("--mode", hook["args"])
                    self.assertIn("warn", hook["args"])

    def test_delegation_recorder_hook_is_retained(self) -> None:
        """The spawn/run evidence recorder is a different class and must stay."""
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = json.dumps(hooks)
        self.assertIn("record-run-context.py", commands)
        self.assertIn("redact-secrets.py", commands)
        for name in ("record-run-context.py", "redact-secrets.py"):
            self.assertTrue((PLUGIN_ROOT / "scripts" / name).exists(), name)

    def test_enforcement_prose_matches_the_restored_guard(self) -> None:
        """Prose and mechanism must agree — they drifted apart twice already.

        v0.30.0 unregistered the hook but left 5 files claiming it still denied
        writes (one of them the reminder injected into every pipeline session).
        Now that enforcement is back, the same files must say so AND must state the
        run-active scope, so nobody re-reads them as "blocks everything".
        """
        for rel in ("skills/full-pipeline/SKILL.md", "skills/measure-coverage/SKILL.md",
                    "references/fallback-policy.md"):
            text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(path=rel):
                self.assertIn("guard-gate-artifacts", text,
                              f"{rel} must document the active enforcement again")
        reminder = (PLUGIN_ROOT / "scripts" / "record-run-context.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("파이프라인이 도는 세션에서만", reminder,
                      "the injected reminder must state the run-active scope")

    def test_settings_json_declares_no_deny_rules(self) -> None:
        """v0.30.0: the recommendation template must not advertise tool blocking.

        Plugin settings.json only applies `agent`/`subagentStatusLine` (official
        constraint), so a deny list here enforced nothing while repeatedly reading
        as "this plugin blocks WebFetch/Read".
        """
        settings = json.loads((PLUGIN_ROOT / "settings.json").read_text(encoding="utf-8"))
        self.assertNotIn("deny", settings.get("permissions", {}))
        self.assertIn("allow", settings["permissions"])

    def test_dead_env_vars_are_gone_from_settings(self) -> None:
        settings = json.loads((PLUGIN_ROOT / "settings.json").read_text(encoding="utf-8"))
        serialized = json.dumps(settings)
        self.assertNotIn("TEST_AUTOEVERMATION_HARNESS_NETWORK", serialized)
        self.assertNotIn("TEST_AUTOEVERMATION_HARNESS_TEST_SCOPE", serialized)
        # The recommended permission block stays — users opt in via their own settings.
        self.assertIn("permissions", settings)

    def test_test_run_offline_enforcement_is_independent_of_hooks(self) -> None:
        """Deleting the hooks must not weaken offline test execution."""
        mcp_config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "0", mcp_config["mcpServers"]["build-test"]["env"]["BUILD_TEST_ALLOW_NETWORK"])
        with mock.patch.dict(os.environ, {"BUILD_TEST_ALLOW_NETWORK": "0"}, clear=False):
            cmd = build_test._build_test_command(
                "gradle", str(PLUGIN_ROOT), "OrderServiceTest",
                with_coverage=True, offline=True)
        self.assertIn("--offline", cmd if isinstance(cmd, str) else " ".join(cmd))


# ------------------------------------------------------------ 2. Windows bootstrap


class BootstrapWindowsLaunchTest(unittest.TestCase):
    """On Windows os.execv would end the process and kill the MCP stdio pipe."""

    def _run_main(self, os_name: str):
        with mock.patch.object(bootstrap.os, "name", os_name), \
                mock.patch.object(bootstrap, "current_interpreter_has_mcp",
                                  return_value=True), \
                mock.patch.object(bootstrap.sys, "argv",
                                  ["bootstrap.py", "server.py", "--flag"]), \
                mock.patch.object(bootstrap.sys, "executable", "/usr/bin/python3"), \
                mock.patch.object(bootstrap.os, "execv") as execv, \
                mock.patch.object(bootstrap.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=7)
            rc = bootstrap.main()
        return rc, execv, run

    def test_windows_uses_subprocess_and_propagates_exit_code(self) -> None:
        rc, execv, run = self._run_main("nt")
        execv.assert_not_called()
        run.assert_called_once_with(["/usr/bin/python3", "server.py", "--flag"])
        self.assertEqual(7, rc)

    def test_posix_still_uses_execv(self) -> None:
        _rc, execv, run = self._run_main("posix")
        run.assert_not_called()
        execv.assert_called_once_with(
            "/usr/bin/python3", ["/usr/bin/python3", "server.py", "--flag"])


# ------------------------------------------------------------------ 3. staleness


class PipelineStateStalenessTest(unittest.TestCase):

    def test_fresh_evidence_still_resumes_at_conformance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_resumable_project(root)
            state = build_test.detect_pipeline_state(tmp)

        self.assertFalse(state["staleness"]["stale"])
        self.assertEqual([], state["staleness"]["reasons"])
        self.assertEqual(9, state["recommendedEntryStage"])

    def test_edited_source_clamps_entry_stage_back_to_test_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_resumable_project(root)
            _touch_future(root / "src" / "main" / "java" / "OrderService.java")
            state = build_test.detect_pipeline_state(tmp)

        staleness = state["staleness"]
        self.assertTrue(staleness["stale"])
        self.assertTrue(staleness["sourceNewerThanJunit"])
        self.assertTrue(staleness["sourceNewerThanJacoco"])
        self.assertIn("JUNIT_STALE", staleness["reasons"])
        self.assertEqual(6, state["recommendedEntryStage"])
        # What already happened is a record, not a recommendation — never clamped.
        self.assertEqual("8", state["highestCompletedStage"])

    def test_changed_build_file_forces_stage_zero_for_profile_redetection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_resumable_project(root)
            workspace = root / "_workspace"
            workspace.mkdir()
            (workspace / "00_config-harness.json").write_text(
                json.dumps({"schemaVersion": 2, "springProfile": {"bootVersion": "2.7.0"}}),
                encoding="utf-8")
            (root / "build.gradle").write_text("plugins { id 'java' }", encoding="utf-8")
            _touch_future(root / "build.gradle")

            state = build_test.detect_pipeline_state(tmp)

        self.assertTrue(state["staleness"]["buildFileNewerThanConfig"])
        self.assertIn("CONFIG_STALE", state["staleness"]["reasons"])
        self.assertEqual(0, state["recommendedEntryStage"])

    def test_same_second_writes_are_not_flagged_stale(self) -> None:
        """Coarse filesystem timestamps must not fake a source change."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_resumable_project(root)
            stamp = time.time()
            for path in (root / "src" / "main" / "java" / "OrderService.java",
                         root / "build" / "test-results" / "test" / "TEST-OrderServiceTest.xml"):
                os.utime(path, (stamp, stamp))
            state = build_test.detect_pipeline_state(tmp)

        self.assertFalse(state["staleness"]["sourceNewerThanJunit"])

    def test_missing_evidence_is_never_reported_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "main" / "java").mkdir(parents=True)
            (root / "src" / "main" / "java" / "A.java").write_text("class A {}",
                                                                   encoding="utf-8")
            state = build_test.detect_pipeline_state(tmp)

        staleness = state["staleness"]
        self.assertFalse(staleness["sourceNewerThanJunit"])
        self.assertFalse(staleness["sourceNewerThanJacoco"])
        self.assertFalse(staleness["stale"])


class StaleStubAllowlistTest(unittest.TestCase):
    """Stale evidence must not earn a durable-resume stub allowance."""

    BASE = {
        "status": "ok",
        "harnessProvenance": True,
        "hasTests": True,
        "scenarios": {"approved": 3},
        "recommendedEntryStage": 9,
        "junitReport": {"present": True, "passed": 5, "failed": 0},
        "jacocoReport": {"present": True, "gatePassed": True},
    }

    def test_fresh_result_allows_run_and_coverage_stubs(self) -> None:
        allowed = recorder._allowed_stub_artifacts(
            {**self.BASE, "staleness": {"stale": False}})
        self.assertIn("06_run_result.json", allowed)
        self.assertIn("08_coverage_result.json", allowed)

    def test_stale_reports_lose_run_and_coverage_stubs(self) -> None:
        allowed = recorder._allowed_stub_artifacts({
            **self.BASE,
            "staleness": {"stale": True, "sourceNewerThanJunit": True,
                          "sourceNewerThanJacoco": True},
        })
        self.assertNotIn("06_run_result.json", allowed)
        self.assertNotIn("08_coverage_result.json", allowed)
        # Test files still exist, so stage 5 need not be regenerated.
        self.assertIn("05_test-gen_files.json", allowed)

    def test_stale_scenarios_lose_the_scenario_stub(self) -> None:
        allowed = recorder._allowed_stub_artifacts({
            **self.BASE,
            "staleness": {"stale": True, "sourceNewerThanScenarios": True},
        })
        self.assertNotIn("04_scenario_set.json", allowed)


# --------------------------------------------------------- 4. multi-module JaCoCo


class MultiModuleJacocoTest(unittest.TestCase):

    def test_submodule_reports_are_aggregated_not_sampled(self) -> None:
        """One fully covered module must not carry an uncovered sibling past the gate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jacoco(root / "moduleA" / "build" / "reports" / "jacoco" / "test"
                          / "jacocoTestReport.xml", missed=0, covered=100)
            _write_jacoco(root / "moduleB" / "build" / "reports" / "jacoco" / "test"
                          / "jacocoTestReport.xml", missed=100, covered=0)

            parsed = build_test.parse_jacoco_report(tmp)
            gate = build_test.coverage_gate(tmp, line=0.95, branch=0.90,
                                            method=0.95, klass=1.0)

        self.assertEqual(2, len(parsed["reportPaths"]))
        self.assertAlmostEqual(0.5, parsed["overall"]["LINE"]["ratio"], places=6)
        self.assertFalse(gate["pass"])

    def test_root_aggregate_report_is_not_double_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jacoco(root / "build" / "reports" / "jacoco" / "test"
                          / "jacocoTestReport.xml", missed=20, covered=80)
            _write_jacoco(root / "moduleA" / "build" / "reports" / "jacoco" / "test"
                          / "jacocoTestReport.xml", missed=0, covered=100)

            parsed = build_test.parse_jacoco_report(tmp)

        self.assertEqual(1, len(parsed["reportPaths"]))
        self.assertAlmostEqual(0.8, parsed["overall"]["LINE"]["ratio"], places=6)

    def test_single_report_keeps_backward_compatible_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jacoco(root / "build" / "reports" / "jacoco" / "test"
                          / "jacocoTestReport.xml", missed=5, covered=95)
            parsed = build_test.parse_jacoco_report(tmp)

        self.assertIn("reportPath", parsed)
        self.assertEqual([parsed["reportPath"]], parsed["reportPaths"])

    def test_unparsable_module_report_fails_instead_of_being_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_jacoco(root / "moduleA" / "build" / "reports" / "jacoco" / "test"
                          / "jacocoTestReport.xml", missed=0, covered=100)
            broken = (root / "moduleB" / "build" / "reports" / "jacoco" / "test"
                      / "jacocoTestReport.xml")
            broken.parent.mkdir(parents=True)
            broken.write_text("<report><unclosed>", encoding="utf-8")

            parsed = build_test.parse_jacoco_report(tmp)

        self.assertEqual("failed", parsed["status"])


# ------------------------------------------------- N. tool-restriction audit doc


class ToolRestrictionAuditDocTest(unittest.TestCase):
    """docs/tool-restrictions.md must stay true as the hook/agent config changes.

    The doc answers "what does this harness block?" so that nobody has to re-read
    the sources. That value evaporates the moment it drifts, so the claims that can
    be machine-checked are machine-checked here.
    """

    DOC = PLUGIN_ROOT / "docs" / "tool-restrictions.md"

    def setUp(self) -> None:
        self.assertTrue(self.DOC.is_file(), "tool-restrictions.md is missing")
        self.text = self.DOC.read_text(encoding="utf-8")

    def test_doc_is_linked_from_readme_and_guide(self) -> None:
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        guide = (PLUGIN_ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("docs/tool-restrictions.md", readme)
        self.assertIn("tool-restrictions.md", guide)

    def test_every_agent_disallowed_tools_row_matches_frontmatter(self) -> None:
        """The Tier 3 table must mirror the actual agents/*.md frontmatter."""
        for agent in sorted((PLUGIN_ROOT / "agents").glob("*.md")):
            name = agent.stem
            frontmatter = agent.read_text(encoding="utf-8").split("---", 2)[1]
            declared = [
                line.split(":", 1)[1].strip()
                for line in frontmatter.splitlines()
                if line.startswith("disallowedTools:")
            ]
            with self.subTest(agent=name):
                self.assertIn(f"`{name}`", self.text,
                              f"{name} is missing from the Tier 3 table")
                if declared:
                    for tool in (t.strip() for t in declared[0].split(",")):
                        self.assertRegex(
                            self.text,
                            rf"`{name}`[^\n]*{tool}",
                            f"{name} row must list disallowedTools {tool}",
                        )

    def test_blocking_hook_inventory_matches_hooks_json(self) -> None:
        """The doc's Tier 1 must list exactly the PreToolUse scripts that can deny."""
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        scripts = {
            arg.rsplit("/", 1)[-1]
            for entry in hooks["hooks"]["PreToolUse"]
            for hook in entry["hooks"]
            for arg in hook.get("args", [])
            if arg.endswith(".py")
        }
        self.assertEqual({"record-run-context.py", "guard-gate-artifacts.py"}, scripts)
        for name in scripts:
            with self.subTest(script=name):
                self.assertIn(name, self.text, f"Tier 1 must document {name}")

    def test_doc_states_posttooluse_cannot_block(self) -> None:
        # Official contract: only PreToolUse can deny; PostToolUse fires after the fact.
        self.assertIn("PostToolUse", self.text)
        self.assertIn("the tool already ran", self.text)

    def test_mcp_env_defaults_quoted_in_doc_match_mcp_json(self) -> None:
        mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        env = {
            key: value
            for server in mcp["mcpServers"].values()
            for key, value in (server.get("env") or {}).items()
        }
        for key in ("BUILD_TEST_ALLOW_NETWORK", "REPO_AST_REQUIRE_JAVAPARSER",
                    "SPEC_DOC_ALLOWLIST", "REPO_AST_ALLOW_ROOT", "SPEC_DOC_REDACT"):
            with self.subTest(env=key):
                self.assertIn(key, env, f"{key} vanished from .mcp.json")
                self.assertIn(key, self.text, f"{key} missing from the Tier 4 table")
        self.assertEqual("0", env["BUILD_TEST_ALLOW_NETWORK"])
        self.assertEqual("1", env["REPO_AST_REQUIRE_JAVAPARSER"])


if __name__ == "__main__":
    unittest.main()
