# Claude 공식 계약 감사 및 SDK 2.x 이전

기준: 2026-09-10. 사용자 승인 계획에 따라 구현 중. 실제 검증 전 완료로 표시하지 않는다.

## 근거와 TODO

| ID | 현재 문제 | 공식 근거 / 구현 방침 | 검증 |
|---|---|---|---|
| R1 | 무제한 mcp 버전 + 제거된 FastMCP import | [SDK migration](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md); MCPServer, >=2.2,<3 | 새 설치/stdio 20도구 |
| R2 | 패키지 존재만 확인, 설치 완료 마커/동시성 | 실제 API import+버전 확인, 가상환경 검증 후 원자 저장/잠금 | 구버전·손상·동시 설치 |
| R3 | SDK2 sync handler 병렬 상태 경쟁 | 원자적 문서 인덱스 교체, 프로젝트별 빌드 잠금 | 동시 요청 |
| H1 | 직접 슬래시 실행 누락 | [Hooks](https://code.claude.com/docs/en/hooks); UserPromptExpansion | slash/Skill 동일 추적 |
| H2 | PreToolUse 시도를 실행 증거로 기록 | SubagentStart 실제 시작; session/run/agent 정확한 연결 | 거부/실패/다른 플러그인 |
| H3 | 실행 종료 누락, 가짜 시간/토큰 | 검증된 최종 산출물/SessionEnd 종료, 관측치만 기록 | 동일 세션 다음 실행 |
| P1 | 하위 에이전트 질문 지시 잔존 | [Subagents](https://code.claude.com/docs/en/sub-agents); 자식 신호/부모 질문 | 전체 프롬프트 계약 |
| P2 | 질문 의사 API, 도구 가용성 시험 호출 | [User input](https://code.claude.com/docs/en/agent-sdk/user-input); questions 배열, 거부≠승인 | 스키마/CI 분기 |
| P3 | unscoped Agent, 가정된 LSP | [Plugins](https://code.claude.com/docs/en/plugins-reference), [Tools](https://code.claude.com/docs/en/tools-reference); 공식 이름/실제 조회 | frontmatter/호출 검사 |
| B1 | task/다중패턴 인터페이스 불일치 | [Gradle](https://docs.gradle.org/current/userguide/java_testing.html), [Failsafe](https://maven.apache.org/surefire/maven-failsafe-plugin/examples/single-test.html) | 단위/통합/한글/다중 |
| B2 | 빈 XML/전부 skipped 성공, 이전 보고서 혼합 | 실제 실행 증거와 결과 상태 통일 | 실패/timeout/보고서 격리 |
| C1 | 범위·제외와 실제 카운터 불일치 | [JaCoCo counters](https://www.jacoco.org/jacoco/trunk/doc/counters.html); 공통 필터 집계 | 측정/게이트/재개 일치 |
| P4 | 저장 권한·setup 책임·정책 간 충돌 | 하네스 자체 정책을 명시; 공식 제약으로 오인 금지 | 전체 문서/예제/코드 대조 |
| W1 | Windows .bat 직접 실행 | [Node child_process](https://nodejs.org/api/child_process.html#spawning-bat-and-cmd-files-on-windows); cmd.exe | Windows 실제 검증 별도 |

- [ ] 전체 파일 전문 검토 및 충돌 기록
- [ ] 결함 회귀 테스트 선행
- [ ] SDK2/실행 환경 수정
- [ ] 훅/도구/프롬프트 계약 수정
- [ ] 실행/커버리지/결과 계약 수정
- [ ] 전체 테스트 + stdio + CLI 통합 검증
- [ ] 미검증 환경과 요구사항별 결과 기록

공식 확장인 사용자 정의 MCP 도구와 하네스 워크플로는 유지한다. 스킬/권한 목록은 파일 경로나 OS 네트워크 격리를 의미하지 않는다. 기존 시나리오 승인 정책은 유지하며 질문 거부를 승인으로 변환하지 않는다.

## 수정 전 재현

- SDK 1.x 격리 환경: 기존 unittest 159개 통과.
- SDK 2.2.0 새 설치: 구형 FastMCP import로 4개 테스트 모듈 로딩 실패.
- 임시 메모리 치환: 서버 3개, 20개 tool 등록과 health 응답 확인(배포 경로 검증 아님).
- direct UserPromptExpansion 추적 누락, Agent PreToolUse만으로 spawn marker 생성 재현.

## 검토 목록

아래는 추적 대상 소스 목록이다. 검토 완료 여부는 담당 검토 결과와 최종 검증 절에서 집계한다. 외부 설치물·빌드 산출물은 제외한다.

- [ ] `.claude-plugin/marketplace.json`
- [ ] `.gitignore`
- [ ] `README.md`
- [ ] `test-autoevermation-harness-plugin/.claude-plugin/plugin.json`
- [ ] `test-autoevermation-harness-plugin/.gitignore`
- [ ] `test-autoevermation-harness-plugin/.lsp.json`
- [ ] `test-autoevermation-harness-plugin/.mcp.json`
- [ ] `test-autoevermation-harness-plugin/CHANGELOG.md`
- [ ] `test-autoevermation-harness-plugin/DEPENDENCIES.md`
- [ ] `test-autoevermation-harness-plugin/README.md`
- [ ] `test-autoevermation-harness-plugin/RESEARCH_NOTES.md`
- [ ] `test-autoevermation-harness-plugin/agents/ast-structure-analyzer.md`
- [ ] `test-autoevermation-harness-plugin/agents/coverage-closer.md`
- [ ] `test-autoevermation-harness-plugin/agents/refactor-advisor.md`
- [ ] `test-autoevermation-harness-plugin/agents/scenario-conformance-verifier.md`
- [ ] `test-autoevermation-harness-plugin/agents/scenario-generator.md`
- [ ] `test-autoevermation-harness-plugin/agents/source-code-analyzer.md`
- [ ] `test-autoevermation-harness-plugin/agents/spec-reviewer.md`
- [ ] `test-autoevermation-harness-plugin/agents/test-code-generator.md`
- [ ] `test-autoevermation-harness-plugin/agents/test-editor.md`
- [ ] `test-autoevermation-harness-plugin/agents/test-fixer.md`
- [ ] `test-autoevermation-harness-plugin/agents/test-runner.md`
- [ ] `test-autoevermation-harness-plugin/docs/GUIDE.md`
- [ ] `test-autoevermation-harness-plugin/docs/pipeline-flow.md`
- [ ] `test-autoevermation-harness-plugin/docs/tool-restrictions.md`
- [ ] `test-autoevermation-harness-plugin/examples/ci/gradle-ci.yml`
- [ ] `test-autoevermation-harness-plugin/examples/ci/maven-ci.yml`
- [ ] `test-autoevermation-harness-plugin/examples/gradle/build-boot2.gradle`
- [ ] `test-autoevermation-harness-plugin/examples/gradle/build.gradle.kts`
- [ ] `test-autoevermation-harness-plugin/examples/java/OrderAmountCalculatorTest.java`
- [ ] `test-autoevermation-harness-plugin/examples/java/OrderControllerTest.java`
- [ ] `test-autoevermation-harness-plugin/examples/java/OrderControllerTest_boot2_junit4.java`
- [ ] `test-autoevermation-harness-plugin/examples/java/OrderControllerTest_boot2_jupiter.java`
- [ ] `test-autoevermation-harness-plugin/examples/json/repair-example.md`
- [ ] `test-autoevermation-harness-plugin/examples/json/scenario-example.json`
- [ ] `test-autoevermation-harness-plugin/examples/json/test-run-result.json`
- [ ] `test-autoevermation-harness-plugin/examples/maven/pom-snippet-boot2.xml`
- [ ] `test-autoevermation-harness-plugin/examples/maven/pom-snippet.xml`
- [ ] `test-autoevermation-harness-plugin/hooks/hooks.json`
- [ ] `test-autoevermation-harness-plugin/hooks/statusline-autosetup.py`
- [ ] `test-autoevermation-harness-plugin/mcp/bootstrap.py`
- [ ] `test-autoevermation-harness-plugin/mcp/build_test_server.py`
- [ ] `test-autoevermation-harness-plugin/mcp/javaparser-cli/.mvn/wrapper/maven-wrapper.properties`
- [ ] `test-autoevermation-harness-plugin/mcp/javaparser-cli/README.md`
- [ ] `test-autoevermation-harness-plugin/mcp/javaparser-cli/mvnw`
- [ ] `test-autoevermation-harness-plugin/mcp/javaparser-cli/mvnw.cmd`
- [ ] `test-autoevermation-harness-plugin/mcp/javaparser-cli/pom.xml`
- [ ] `test-autoevermation-harness-plugin/mcp/javaparser-cli/src/main/java/com/example/harness/AstCli.java`
- [ ] `test-autoevermation-harness-plugin/mcp/jdtls-launcher.cjs`
- [ ] `test-autoevermation-harness-plugin/mcp/launch.cjs`
- [ ] `test-autoevermation-harness-plugin/mcp/pyproject.toml`
- [ ] `test-autoevermation-harness-plugin/mcp/repo_ast_server.py`
- [ ] `test-autoevermation-harness-plugin/mcp/requirements.txt`
- [ ] `test-autoevermation-harness-plugin/mcp/run-server.sh`
- [ ] `test-autoevermation-harness-plugin/mcp/spec_doc_server.py`
- [ ] `test-autoevermation-harness-plugin/references/agent-result-envelope.md`
- [ ] `test-autoevermation-harness-plugin/references/build-provisioning.md`
- [ ] `test-autoevermation-harness-plugin/references/custom-components.md`
- [ ] `test-autoevermation-harness-plugin/references/environment-setup.md`
- [ ] `test-autoevermation-harness-plugin/references/fallback-policy.md`
- [ ] `test-autoevermation-harness-plugin/references/refactor-advisory.md`
- [ ] `test-autoevermation-harness-plugin/references/scenario-docs.md`
- [ ] `test-autoevermation-harness-plugin/references/test-code-invariants.md`
- [ ] `test-autoevermation-harness-plugin/references/version-compatibility.md`
- [ ] `test-autoevermation-harness-plugin/scripts/dev/probe-hook-stdin.py`
- [ ] `test-autoevermation-harness-plugin/scripts/guard-gate-artifacts.py`
- [ ] `test-autoevermation-harness-plugin/scripts/persist_astcli_jar.py`
- [ ] `test-autoevermation-harness-plugin/scripts/record-run-context.py`
- [ ] `test-autoevermation-harness-plugin/scripts/record-timing.py`
- [ ] `test-autoevermation-harness-plugin/scripts/redact-secrets.py`
- [ ] `test-autoevermation-harness-plugin/scripts/setup_jdtls.py`
- [ ] `test-autoevermation-harness-plugin/scripts/test-autoevermation-statusline-launch.cjs`
- [ ] `test-autoevermation-harness-plugin/scripts/test-autoevermation-statusline.py`
- [ ] `test-autoevermation-harness-plugin/settings.json`
- [ ] `test-autoevermation-harness-plugin/skills/analyze-ast/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/analyze-source/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/configure-harness/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/edit-tests/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/full-pipeline/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/full-pipeline/references/orchestration-detail.md`
- [ ] `test-autoevermation-harness-plugin/skills/generate-scenarios/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/generate-tests/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/ingest-specs/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/measure-coverage/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/refactor-advisory/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/repair-tests/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/run-tests/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/setup-harness/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/setup-statusline/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/skills/verify-scenarios/SKILL.md`
- [ ] `test-autoevermation-harness-plugin/tests/test_env_and_staleness.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_mutation_removal.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_official_contract.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_pipeline_state_contract.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_pipeline_v2.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_result_verification_upgrade.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_setup_harness_split.py`
- [ ] `test-autoevermation-harness-plugin/tests/test_update_persistence.py`
