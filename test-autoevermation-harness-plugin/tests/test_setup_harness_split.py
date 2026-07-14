"""환경 세팅(setup-harness) 분리 계약 테스트 (v0.24.0).

세팅과 실행의 분리가 프롬프트 계약 수준에서 실제로 지켜지는지 검증한다:
  - setup-harness 스킬이 E1~E10 + 상태줄(S1)을 소유한다
  - configure-harness/full-pipeline은 세팅하지 않고 E-verify 프로브만 돌린다
  - 미완료 시 고정 안내 문자열로 하드 중단한다

표준 라이브러리만 사용한다(tests/test_optional_pitest.py와 동일 패턴).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]

SKILLS = PLUGIN_ROOT / "skills"
REFERENCES = PLUGIN_ROOT / "references"

# 파이프라인이 세팅 미완료 시 반드시 안내해야 하는 고정 문자열(계약).
GUIDANCE = "먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class SetupHarnessSkillTests(unittest.TestCase):
    """setup-harness가 환경 세팅의 단독 수행 주체다."""

    def setUp(self) -> None:
        self.path = SKILLS / "setup-harness" / "SKILL.md"
        self.assertTrue(self.path.is_file(), "skills/setup-harness/SKILL.md 가 없다")
        self.text = _read(self.path)

    def test_frontmatter_declares_skill_name(self) -> None:
        self.assertTrue(self.text.startswith("---\n"))
        head = self.text.split("---", 2)[1]
        self.assertIn("name: setup-harness", head)
        self.assertIn("description:", head)

    def test_owns_setup_items_e1_through_e10(self) -> None:
        for item in ("E1", "E2", "E3", "E3b", "E4", "E5", "E6", "E7", "E10"):
            with self.subTest(item=item):
                self.assertIn(item, self.text)

    def test_verifies_mcp_connection_with_three_health_calls(self) -> None:
        for server in ("repo-ast-mcp.health", "spec-doc-mcp.health", "build-test-mcp.health"):
            with self.subTest(server=server):
                self.assertIn(server, self.text)

    def test_installs_statusline_via_autosetup_script(self) -> None:
        self.assertIn("statusline-autosetup.py", self.text)
        self.assertIn("--consent granted", self.text)
        # 이전 거절(consent=declined)을 임의로 뒤집지 않는다.
        self.assertIn("declined", self.text)

    def test_points_to_environment_setup_ssot_instead_of_duplicating_table(self) -> None:
        self.assertIn("environment-setup.md", self.text)
        # E 항목 표를 재복제하지 않는다(SSOT 원칙, v0.21).
        self.assertNotIn("| E1 |", self.text)

    def test_does_not_own_build_capability_provisioning(self) -> None:
        # E11/E12는 mutation.enabled 인터뷰 결과에 의존 → configure-harness 0.6 소관.
        self.assertNotIn("detect_build_capabilities", self.text)
        self.assertNotIn("check_dependency_cache", self.text)

    def test_declares_main_loop_only(self) -> None:
        # MCP health / AskUserQuestion 은 서브에이전트에서 불가.
        self.assertIn("위임 금지", self.text)


class ConfigureHarnessGateTests(unittest.TestCase):
    """configure-harness는 검증만 하고 세팅하지 않는다."""

    def setUp(self) -> None:
        self.text = _read(SKILLS / "configure-harness" / "SKILL.md")

    def test_phase_e_execution_block_is_gone(self) -> None:
        self.assertNotIn("| E1 |", self.text)  # Phase E 실행 표
        self.assertNotIn("Preflight 단계 (Phase E)", self.text)
        self.assertNotIn("repo-ast-mcp.health()", self.text)  # E3b 실행 블록

    def test_has_e_verify_gate_with_guidance(self) -> None:
        self.assertIn("E-verify", self.text)
        self.assertIn(GUIDANCE, self.text)

    def test_delegates_setup_to_setup_harness(self) -> None:
        self.assertIn("setup-harness", self.text)

    def test_retains_stage_0_6_build_provisioning(self) -> None:
        self.assertIn("0.6단계", self.text)
        self.assertIn("detect_build_capabilities", self.text)
        self.assertIn("check_dependency_cache", self.text)

    def test_retains_stage_0_5_profile_detection(self) -> None:
        self.assertIn("detect_spring_profile", self.text)


class FullPipelineGateTests(unittest.TestCase):
    """full-pipeline은 세팅하지 않고 E-verify 게이트로 하드 중단한다."""

    def setUp(self) -> None:
        self.text = _read(SKILLS / "full-pipeline" / "SKILL.md")

    def test_has_e_verify_gate_with_guidance(self) -> None:
        self.assertIn("E-verify", self.text)
        self.assertIn(GUIDANCE, self.text)

    def test_no_longer_attributes_phase_e_setup_to_configure_harness(self) -> None:
        self.assertNotIn("수행 주체는 configure-harness다", self.text)
        self.assertNotIn("Phase E: 환경 세팅", self.text)

    def test_resume_path_runs_probes_itself(self) -> None:
        # 재사용·재개 경로에서 configure-harness를 건너뛰면 오케스트레이터가 직접 검증해야 한다
        # (MCP 등록은 세션 단위라 이전 실행의 통과가 이번 세션을 보장하지 않는다).
        self.assertIn("재사용·재개 경로", self.text)
        self.assertIn("세션 단위", self.text)

    def test_does_not_auto_delegate_setup(self) -> None:
        self.assertIn("자동 위임", self.text)  # "자동 위임 금지" 계약


class EnvironmentSetupSsotTests(unittest.TestCase):
    """environment-setup.md가 수행 주체와 E-verify 프로브의 SSOT다."""

    def setUp(self) -> None:
        self.text = _read(REFERENCES / "environment-setup.md")

    def test_declares_setup_harness_as_performer(self) -> None:
        self.assertIn("setup-harness", self.text)

    def test_defines_e_verify_probe_section(self) -> None:
        self.assertIn("E-verify", self.text)
        self.assertIn(GUIDANCE, self.text)

    def test_probe_uses_check_only_for_jdtls(self) -> None:
        # 검증 프로브는 설치하지 않는다 — setup_jdtls.py --check-only.
        self.assertIn("--check-only", self.text)

    def test_probe_uses_live_health_calls(self) -> None:
        self.assertIn("health", self.text)


class JdtlsProbeTests(unittest.TestCase):
    """E-verify가 의존하는 --check-only 플래그가 실제로 존재한다."""

    def test_setup_jdtls_supports_check_only(self) -> None:
        script = _read(PLUGIN_ROOT / "scripts" / "setup_jdtls.py")
        self.assertIn("--check-only", script)


class ManifestAndDocsTests(unittest.TestCase):
    def test_plugin_version_bumped(self) -> None:
        manifest = json.loads(_read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json"))
        self.assertEqual(manifest["version"], "0.24.0")
        # 스킬은 skills/ 디렉터리에서 자동 발견된다(공식 플러그인 규약).
        self.assertEqual(manifest["skills"], "./skills")

    def test_docs_reference_setup_harness(self) -> None:
        for rel in ("README.md", "docs/GUIDE.md", "docs/pipeline-flow.md"):
            with self.subTest(doc=rel):
                self.assertIn("setup-harness", _read(PLUGIN_ROOT / rel))

    def test_changelog_has_0_24_0_entry(self) -> None:
        self.assertIn("## [0.24.0]", _read(PLUGIN_ROOT / "CHANGELOG.md"))


if __name__ == "__main__":
    unittest.main()
