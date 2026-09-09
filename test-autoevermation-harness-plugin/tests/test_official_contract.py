"""v0.34.0 — Claude Code 공식 계약 정합 회귀 가드.

공식 문서(https://code.claude.com/docs/en/{sub-agents,skills,hooks,tools-reference,worktrees})
근거로 정정한 항목이 다시 흘러들어오지 않도록 지킨다:

* 위임 의사코드는 ``Agent(`` 이며 ``Task(``/``model="inherit"`` 인자를 쓰지 않는다
  (Task는 v2.1.63에 Agent로 개명된 alias, Agent 도구 model 파라미터에 inherit 값 없음).
* 비대화형 감지에 비공식 환경변수(``CLAUDE_NO_PROMPT``)나 ``TodoWrite`` 지시를 쓰지 않는다.
* agents/skills frontmatter 키는 공식 집합 안에 있고, 어떤 에이전트도 ``isolation``을 쓰지 않는다
  (worktree는 원격 기본 브랜치의 추적 파일만 체크아웃 → 미커밋 테스트가 보이지 않음).
* redact-secrets.py 훅(envelope) 모드는 exit 0 + PostToolUse ``additionalContext`` JSON.
* guard-gate-artifacts.py Zone B: 오케스트레이터(agent_type 없음)의 src/test/java Edit는
  spawn-test-fixer 마커가 있어도 deny(오케스트레이터 patch-apply 예외 제거).
* 문서 간 모순 정정분(C1/C4/C5/H1)의 재발 가드.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
AGENTS = sorted((PLUGIN_ROOT / "agents").glob("*.md"))
SKILLS = sorted((PLUGIN_ROOT / "skills").rglob("*.md"))
PROSE = AGENTS + SKILLS + sorted((PLUGIN_ROOT / "references").glob("*.md")) + sorted(
    (PLUGIN_ROOT / "docs").glob("*.md")
) + [PLUGIN_ROOT / "README.md", PLUGIN_ROOT / "DEPENDENCIES.md"]

# https://code.claude.com/docs/en/sub-agents — Supported frontmatter fields
OFFICIAL_AGENT_KEYS = {
    "name", "description", "tools", "disallowedTools", "model", "permissionMode",
    "maxTurns", "skills", "mcpServers", "hooks", "memory", "background", "effort",
    "isolation", "color", "initialPrompt", "experimental",
}
# https://code.claude.com/docs/en/skills — Frontmatter reference
OFFICIAL_SKILL_KEYS = {
    "name", "description", "when_to_use", "argument-hint", "arguments",
    "disable-model-invocation", "user-invocable", "allowed-tools", "disallowed-tools",
    "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
    "metadata", "license", "compatibility",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter_keys(path: Path) -> set[str]:
    lines = _read(path).splitlines()
    assert lines and lines[0] == "---", path
    keys = set()
    for line in lines[1:]:
        if line == "---":
            break
        m = re.match(r"^([A-Za-z_-]+):", line)
        if m:
            keys.add(m.group(1))
    return keys


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate_guard = _load_module("official_contract_gate_guard", PLUGIN_ROOT / "scripts" / "guard-gate-artifacts.py")


class DelegationPseudoCodeTests(unittest.TestCase):
    def test_skills_delegate_with_agent_tool_not_task(self) -> None:
        for path in PROSE:
            text = _read(path)
            with self.subTest(doc=path.relative_to(PLUGIN_ROOT)):
                self.assertNotIn("Task(", text, "Task는 Agent의 구 alias — 의사코드는 Agent( 로 통일")
                self.assertNotIn('model="inherit"', text,
                                 "Agent 도구 model 파라미터에 inherit 값은 없다(frontmatter 전용)")
        # 위임이 있는 스킬은 Agent(subagent_type=...)를 쓴다
        delegating = [p for p in SKILLS if "subagent_type=" in _read(p)]
        self.assertGreaterEqual(len(delegating), 12)
        for path in delegating:
            self.assertIn("Agent(", _read(path), path.name)

    def test_hook_hint_strings_use_agent_tool_name(self) -> None:
        for rel in ("scripts/guard-gate-artifacts.py", "scripts/record-run-context.py"):
            text = _read(PLUGIN_ROOT / rel)
            with self.subTest(script=rel):
                self.assertNotIn("Task(subagent_type", text)
        # alias 호환은 유지한다(구버전 세션의 tool_name)
        self.assertIn('("Task", "Agent")', _read(PLUGIN_ROOT / "scripts" / "record-run-context.py"))
        hooks = json.loads(_read(PLUGIN_ROOT / "hooks" / "hooks.json"))
        matchers = [e.get("matcher") for e in hooks["hooks"]["PreToolUse"]]
        self.assertIn("Skill|Task|Agent", matchers)


class NonInteractiveDetectionTests(unittest.TestCase):
    def test_no_unofficial_env_or_todo_tool_instructions(self) -> None:
        for path in PROSE:
            text = _read(path)
            with self.subTest(doc=path.relative_to(PLUGIN_ROOT)):
                self.assertNotIn("CLAUDE_NO_PROMPT", text)
                # 설명문("TodoWrite는 쓰지 않는다")만 허용하고, 사용 지시는 금지
                for m in re.finditer(r"TodoWrite[^\n]{0,12}", text):
                    self.assertRegex(m.group(0), r"TodoWrite(`|는 |·)", "TodoWrite 사용 지시 금지: %s" % m.group(0))

    def test_detection_rule_is_tool_availability_based(self) -> None:
        text = _read(PLUGIN_ROOT / "skills" / "configure-harness" / "SKILL.md")
        self.assertIn("도구 목록에 `AskUserQuestion`이 **없는** 경우", text)
        self.assertIn("첫 `AskUserQuestion` 호출이 차단·거부", text)
        self.assertNotIn("환경 변수 `CI=true`", text)


class FrontmatterContractTests(unittest.TestCase):
    def test_agent_frontmatter_keys_are_official(self) -> None:
        for path in AGENTS:
            keys = _frontmatter_keys(path)
            with self.subTest(agent=path.name):
                self.assertTrue(keys <= OFFICIAL_AGENT_KEYS, keys - OFFICIAL_AGENT_KEYS)
                self.assertNotIn("isolation", keys,
                                 "worktree는 미커밋 테스트를 볼 수 없다(worktrees 문서) — v0.34.0에서 제거")
                self.assertIn("model", keys)

    def test_skill_frontmatter_keys_are_official(self) -> None:
        for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md"):
            keys = _frontmatter_keys(path)
            with self.subTest(skill=path.parent.name):
                self.assertTrue(keys <= OFFICIAL_SKILL_KEYS, keys - OFFICIAL_SKILL_KEYS)


class RedactSecretsHookOutputTests(unittest.TestCase):
    SCRIPT = PLUGIN_ROOT / "scripts" / "redact-secrets.py"

    def _run(self, stdin: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), "--mode", "warn"],
            input=stdin, capture_output=True, text=True, check=False,
        )

    def test_hook_envelope_reports_via_additional_context_and_exit_zero(self) -> None:
        envelope = json.dumps({
            "tool_name": "Write",
            "tool_input": {"file_path": "src/test/java/XTest.java",
                           "content": 'String password = "abc123";'},
            "session_id": "s", "cwd": ".",
        })
        proc = self._run(envelope)
        self.assertEqual(0, proc.returncode, proc.stderr)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual("PostToolUse", out["hookSpecificOutput"]["hookEventName"])
        self.assertIn("password", out["hookSpecificOutput"]["additionalContext"])
        self.assertIn("XTest.java", out["systemMessage"])

    def test_hook_envelope_without_findings_is_silent(self) -> None:
        proc = self._run(json.dumps({"tool_name": "Write",
                                     "tool_input": {"file_path": "a.java", "content": "int x = 1;"}}))
        self.assertEqual(0, proc.returncode)
        self.assertEqual("", proc.stdout.strip())

    def test_cli_text_mode_keeps_nonzero_exit(self) -> None:
        proc = self._run('String password = "abc123";\n')
        self.assertEqual(1, proc.returncode)
        self.assertEqual("", proc.stdout.strip())


class ZoneBOrchestratorEditTests(unittest.TestCase):
    def _decide(self, agent_type: str, tool_name: str, with_fixer_marker: bool) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markers = root / "_workspace" / ".markers"
            markers.mkdir(parents=True)
            (markers / "run.json").write_text(json.dumps({"session_id": "session"}), encoding="utf-8")
            if with_fixer_marker:
                (markers / "spawn-test-fixer.json").write_text(
                    json.dumps({"session_id": "session"}), encoding="utf-8")
            for name in ("04_scenario_set.json", "04b_approval.json"):
                (root / "_workspace" / name).write_text("{}", encoding="utf-8")
            test_file = root / "src" / "test" / "java" / "com" / "example" / "OrderServiceTest.java"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("class OrderServiceTest {}", encoding="utf-8")
            payload = {
                "tool_name": tool_name,
                "tool_input": {"file_path": str(test_file), "old_string": "a", "new_string": "b"},
                "session_id": "session", "cwd": tmp,
            }
            if agent_type:
                payload["agent_type"] = agent_type
            output = io.StringIO()
            with mock.patch.object(gate_guard.sys, "stdin", io.StringIO(json.dumps(payload))):
                with redirect_stdout(output):
                    gate_guard.main()
            return json.loads(output.getvalue())

    def test_orchestrator_edit_is_denied_even_with_spawn_test_fixer_marker(self) -> None:
        decision = self._decide(agent_type="", tool_name="Edit", with_fixer_marker=True)
        self.assertEqual("deny", decision["hookSpecificOutput"]["permissionDecision"])
        self.assertIn("test-fixer", decision["hookSpecificOutput"]["permissionDecisionReason"])

    def test_test_fixer_edit_is_allowed(self) -> None:
        self.assertEqual({}, self._decide(agent_type="test-fixer", tool_name="Edit", with_fixer_marker=True))

    def test_zone_b_docs_list_matches_code(self) -> None:
        self.assertEqual({"test-code-generator", "coverage-closer", "test-fixer", "test-editor"},
                         set(gate_guard.TEST_WRITE_AGENTS))
        docstring = _read(PLUGIN_ROOT / "scripts" / "guard-gate-artifacts.py")
        self.assertIn("{test-code-generator, coverage-closer, test-fixer, test-editor}", docstring)
        self.assertNotIn("allow (7/9.5단계 patch-apply)", docstring)
        pipeline = _read(PLUGIN_ROOT / "skills" / "full-pipeline" / "SKILL.md")
        self.assertIn("test-code-generator·coverage-closer·test-fixer·test-editor", pipeline)
        self.assertNotIn("test-fixer patch 적용 Edit", pipeline)


class ContradictionRegressionTests(unittest.TestCase):
    def test_c1_orchestrator_does_not_write_generated_tests(self) -> None:
        text = _read(PLUGIN_ROOT / "skills" / "generate-tests" / "SKILL.md")
        self.assertNotIn("`path` 경로에 Write한다", text)
        self.assertIn("다시 Write하지 않는다", text)

    def test_c4_empty_target_scope_is_a_signal_not_run_all(self) -> None:
        self.assertNotIn("비어 있을 때만 fallback", _read(PLUGIN_ROOT / "skills" / "run-tests" / "SKILL.md"))
        self.assertNotIn("비어 있을 때만 fallback", _read(PLUGIN_ROOT / "skills" / "full-pipeline" / "SKILL.md"))
        run_tests = _read(PLUGIN_ROOT / "skills" / "run-tests" / "SKILL.md")
        self.assertIn("TARGET_SCOPE_UNSPECIFIED", run_tests)
        self.assertNotIn("전체 task는 fallback", run_tests)

    def test_c5_no_silent_gradle_default(self) -> None:
        self.assertNotIn("기본 Gradle 가정", _read(PLUGIN_ROOT / "skills" / "generate-tests" / "SKILL.md"))
        self.assertNotIn("Gradle/Maven 양쪽으로 병기", _read(PLUGIN_ROOT / "agents" / "test-code-generator.md"))

    def test_h1_max_repair_retries_default_is_three(self) -> None:
        self.assertIn('"maxRepairRetries": 3', _read(PLUGIN_ROOT / "skills" / "configure-harness" / "SKILL.md"))

    def test_no_regex_fallback_residue_in_prose(self) -> None:
        for path in PROSE + [PLUGIN_ROOT / "mcp" / "pyproject.toml"]:
            with self.subTest(doc=path.relative_to(PLUGIN_ROOT)):
                self.assertNotIn("regex 폴백", _read(path))

    def test_test_fixer_has_no_worktree_remap_path(self) -> None:
        text = _read(PLUGIN_ROOT / "skills" / "full-pipeline" / "SKILL.md")
        self.assertNotIn("메인 트리에 적용", text)
        self.assertNotIn("patches[] 메인 반영", _read(PLUGIN_ROOT / "docs" / "pipeline-flow.md"))
        self.assertNotIn("Edit으로 적용한다", _read(PLUGIN_ROOT / "skills" / "repair-tests" / "SKILL.md"))
        self.assertNotIn("isolation", _frontmatter_keys(PLUGIN_ROOT / "agents" / "test-fixer.md"))


if __name__ == "__main__":
    unittest.main()
