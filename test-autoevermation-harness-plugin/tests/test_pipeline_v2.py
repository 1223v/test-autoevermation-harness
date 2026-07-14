from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
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


gate_guard = _load_module(
    "pipeline_v2_gate_guard",
    PLUGIN_ROOT / "scripts" / "guard-gate-artifacts.py",
)
statusline = _load_module(
    "pipeline_v2_statusline",
    PLUGIN_ROOT / "scripts" / "test-autoevermation-statusline.py",
)
record_context = _load_module(
    "pipeline_v2_record_context",
    PLUGIN_ROOT / "scripts" / "record-run-context.py",
)


class RemovedComponentContractTests(unittest.TestCase):
    def test_removed_skill_and_agent_are_absent(self) -> None:
        self.assertFalse((PLUGIN_ROOT / "skills" / "mutation-test").exists())
        self.assertFalse((PLUGIN_ROOT / "agents" / "mutation-analyst.md").exists())
        self.assertEqual(14, len([p for p in (PLUGIN_ROOT / "skills").iterdir() if p.is_dir()]))
        self.assertEqual(10, len(list((PLUGIN_ROOT / "agents").glob("*.md"))))

    def test_pipeline_contract_has_no_mutation_branch(self) -> None:
        for rel in (
            "skills/configure-harness/SKILL.md",
            "skills/full-pipeline/SKILL.md",
            "scripts/guard-gate-artifacts.py",
            "scripts/record-run-context.py",
        ):
            text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8").lower()
            with self.subTest(path=rel):
                self.assertNotIn("pitest", text)
                self.assertNotIn("mutation-analyst", text)
                self.assertNotIn("mutation-test", text)
                self.assertNotIn("09_mutation_result", text)

    def test_manifest_uses_release_version(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual("0.25.0", manifest["version"])


class ArtifactSequenceTests(unittest.TestCase):
    def _activate_run(self, workspace: Path, session_id: str = "session") -> None:
        markers = workspace / ".markers"
        markers.mkdir(parents=True)
        (markers / "run.json").write_text(
            json.dumps({"session_id": session_id}), encoding="utf-8"
        )

    def test_conformance_sequence_is_physically_enforced(self) -> None:
        self.assertEqual(
            ("08_coverage_result.json",),
            gate_guard.SEQUENCE_PRECONDITIONS["09_conformance.json"],
        )
        self.assertEqual(
            ("09_conformance.json",),
            gate_guard.SEQUENCE_PRECONDITIONS["09b_conformance_repair.json"],
        )
        self.assertEqual(
            "scenario-conformance-verifier",
            gate_guard.PRODUCERS["09_conformance.json"],
        )

    def test_guard_rejects_conformance_without_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()
            self._activate_run(workspace)

            message = gate_guard._zone_a(
                "09_conformance.json",
                "Write",
                {"content": "{}"},
                str(workspace),
                "session",
                "scenario-conformance-verifier",
            )

        self.assertIn("08_coverage_result.json", message)

    def test_guard_allows_conformance_after_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()
            self._activate_run(workspace)
            (workspace / "08_coverage_result.json").write_text("{}", encoding="utf-8")

            message = gate_guard._zone_a(
                "09_conformance.json",
                "Write",
                {"content": "{}"},
                str(workspace),
                "session",
                "scenario-conformance-verifier",
            )

        self.assertEqual("", message)

    def test_guard_rejects_repair_without_conformance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()
            self._activate_run(workspace)

            message = gate_guard._zone_a(
                "09b_conformance_repair.json",
                "Write",
                {"content": "{}"},
                str(workspace),
                "session",
                "",
            )

        self.assertIn("09_conformance.json", message)

    def test_guard_requires_schema_v2_for_config_regardless_of_legacy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    message = gate_guard._zone_a(
                        "00_config-harness.json",
                        "Write",
                        {
                            "content": json.dumps(
                                {
                                    "springProfile": {},
                                    "mutation": {"enabled": enabled},
                                }
                            )
                        },
                        str(workspace),
                        "session",
                        "",
                    )
                    self.assertIn("schemaVersion=2", message)

    def test_durable_stub_cannot_forge_stage_9(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()
            self._activate_run(workspace)
            (workspace / ".markers" / "pipeline-state.detected.json").write_text(
                json.dumps({"session_id": "session"}), encoding="utf-8"
            )

            message = gate_guard._zone_a(
                "09_conformance.json",
                "Write",
                {"content": json.dumps({"source": "durable-scan"})},
                str(workspace),
                "session",
                "",
            )

        self.assertIn("위임 없이 산출물 기록", message)

    def test_pipeline_result_requires_stage_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()

            message = gate_guard._zone_a(
                "pipeline_result.json",
                "Write",
                {"content": json.dumps({"schemaVersion": 2, "status": "ok"})},
                str(workspace),
                "session",
                "",
            )

        self.assertIn("stages.verifyScenarios", message)

    def test_empty_conformance_cannot_complete_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "_workspace")
            workspace.mkdir()
            (workspace / "09_conformance.json").write_text("{}", encoding="utf-8")
            payload = {
                "schemaVersion": 2,
                "status": "ok",
                "summary": "complete",
                "stages": {"verifyScenarios": {"status": "ok"}},
            }

            message = gate_guard._zone_a(
                "pipeline_result.json",
                "Write",
                {"content": json.dumps(payload)},
                str(workspace),
                "session",
                "",
            )

        self.assertIn("집계값", message)

    def test_pipeline_named_file_outside_workspace_is_not_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "config", "pipeline_result.json")
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": str(target), "content": "{}"},
                "session_id": "session",
                "cwd": tmp,
            }
            output = io.StringIO()
            with mock.patch.object(gate_guard.sys, "stdin", io.StringIO(json.dumps(payload))):
                with redirect_stdout(output):
                    gate_guard.main()

        self.assertEqual({}, json.loads(output.getvalue()))

    def test_statusline_uses_new_tail_order(self) -> None:
        self.assertIn(
            ("08_coverage_result.json", "stage 9: verify-scenarios"),
            statusline.ORDER,
        )
        self.assertIn(
            ("09_conformance.json", "aggregating report"),
            statusline.ORDER,
        )
        self.assertNotIn("09_mutation_result.json", {item[0] for item in statusline.ORDER})
        self.assertEqual("09b_conformance_repair.json", statusline.CONFORMANCE_REPAIR_ARTIFACT)


class StatuslineMigrationTests(unittest.TestCase):
    def _line(self, root: Path) -> str:
        payload = json.dumps({"workspace": {"current_dir": str(root)}}).encode()
        return statusline.harness_line(None, payload)

    def test_legacy_artifacts_and_result_do_not_complete_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "_workspace"
            workspace.mkdir()
            for name in (
                "09_mutation_result.json",
                "10_conformance.json",
                "10b_conformance_repair.json",
            ):
                (workspace / name).write_text("{}", encoding="utf-8")
            (workspace / "pipeline_result.json").write_text(
                json.dumps({"status": "ok"}), encoding="utf-8"
            )

            line = self._line(root)

        self.assertNotIn("done", line)
        self.assertNotIn("mutation", line.lower())
        self.assertNotIn("stage 10", line.lower())

    def test_minimal_schema_v2_result_does_not_complete_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "_workspace"
            workspace.mkdir()
            (workspace / "pipeline_result.json").write_text(
                json.dumps({"schemaVersion": 2, "status": "ok"}), encoding="utf-8"
            )

            line = self._line(root)

        self.assertNotIn("done", line)

    def test_empty_conformance_does_not_complete_statusline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "_workspace"
            workspace.mkdir()
            (workspace / "09_conformance.json").write_text("{}", encoding="utf-8")
            (workspace / "pipeline_result.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "status": "ok",
                        "summary": "complete",
                        "stages": {"verifyScenarios": {"status": "ok"}},
                    }
                ),
                encoding="utf-8",
            )

            line = self._line(root)

        self.assertNotIn("done", line)

    def test_valid_schema_v2_result_completes_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "_workspace"
            workspace.mkdir()
            totals = {"approved": 1, "satisfied": 1, "unsatisfied": 0, "missing": 0}
            (workspace / "09_conformance.json").write_text(
                json.dumps({"status": "ok", "totals": totals}), encoding="utf-8"
            )
            (workspace / "pipeline_result.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "status": "ok",
                        "summary": "all scenarios satisfied",
                        "stages": {"verifyScenarios": {"status": "ok", **totals}},
                    }
                ),
                encoding="utf-8",
            )

            line = self._line(root)

        self.assertIn("done (ok)", line)

    def test_early_partial_with_explicit_skipped_conformance_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "_workspace"
            workspace.mkdir()
            result = {
                "schemaVersion": 2,
                "status": "partial",
                "summary": "all scenarios were excluded before generation",
                "stages": {"verifyScenarios": {"status": "skipped"}},
            }
            guard_message = gate_guard._zone_a(
                "pipeline_result.json",
                "Write",
                {"content": json.dumps(result)},
                str(workspace),
                "session",
                "",
            )
            (workspace / "pipeline_result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )

            line = self._line(root)

        self.assertEqual("", guard_message)
        self.assertIn("done (partial)", line)

    def test_new_artifacts_drive_tail_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "_workspace"
            workspace.mkdir()
            (workspace / "08_coverage_result.json").write_text("{}", encoding="utf-8")
            self.assertIn("stage 9: verify-scenarios", self._line(root))

            (workspace / "09_conformance.json").write_text("{}", encoding="utf-8")
            self.assertIn("aggregating report", self._line(root))

            (workspace / "09b_conformance_repair.json").write_text("{}", encoding="utf-8")
            self.assertIn("stage 9.5: conformance-repair", self._line(root))

    def test_legacy_resume_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "_resume.json").write_text(
                json.dumps({"entryStage": 9, "entryLabel": "stage 9: mutation-test"}),
                encoding="utf-8",
            )

            self.assertIsNone(statusline._read_resume(str(workspace)))

    def test_schema_v2_resume_can_enter_stage_9(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "_resume.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "entryStage": 9,
                        "entryLabel": "stage 9: verify-scenarios",
                    }
                ),
                encoding="utf-8",
            )

            resume = statusline._read_resume(str(workspace))

        self.assertIsNotNone(resume)
        self.assertEqual(9, resume["entryStage"])


class RunMarkerTests(unittest.TestCase):
    def test_reinvocation_clears_spawn_and_detect_markers_in_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            markers = Path(tmp, "_workspace", ".markers")
            markers.mkdir(parents=True)
            for name in (
                "run.json",
                "spawn-scenario-conformance-verifier.json",
                "pipeline-state.detected.json",
            ):
                (markers / name).write_text(
                    json.dumps({"session_id": "same-session"}), encoding="utf-8"
                )
            output = io.StringIO()
            with redirect_stdout(output):
                record_context._handle_skill(
                    {"cwd": tmp},
                    {"skill": "test-autoevermation-harness-plugin:full-pipeline"},
                    "same-session",
                )

            run = json.loads((markers / "run.json").read_text(encoding="utf-8"))
            spawn_exists = (markers / "spawn-scenario-conformance-verifier.json").exists()
            detect_exists = (markers / "pipeline-state.detected.json").exists()

        self.assertEqual("same-session", run["session_id"])
        self.assertFalse(spawn_exists)
        self.assertFalse(detect_exists)
        self.assertIn("additionalContext", output.getvalue())


if __name__ == "__main__":
    unittest.main()
