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

    def test_delegation_enforcement_hooks_are_retained(self) -> None:
        """The anti-hallucination hooks are a different class and must stay."""
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = json.dumps(hooks)
        self.assertIn("record-run-context.py", commands)
        self.assertIn("guard-gate-artifacts.py", commands)
        self.assertIn("redact-secrets.py", commands)
        for name in ("record-run-context.py", "guard-gate-artifacts.py",
                     "redact-secrets.py"):
            self.assertTrue((PLUGIN_ROOT / "scripts" / name).exists(), name)

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


if __name__ == "__main__":
    unittest.main()
