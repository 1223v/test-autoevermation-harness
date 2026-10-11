---
name: full-pipeline
description: Spring 테스트를 새로 생성·재생성하거나 하네스의 실패·커버리지 부족을 개선하라는 명시적 요청에 사용한다. 승인 시나리오 생성, 실행, JaCoCo 측정, 적합성 확인을 연결한다. 단순 테스트 실행은 run-tests, 커버리지 측정은 measure-coverage, 시나리오 확인은 verify-scenarios를 사용한다. 하네스 맥락 없는 보완·업데이트·재실행에는 활성화하지 않는다.
---

## 실행 계약

[호스트 실행 계약](../../references/host-runtime.md)과 [공용 실행 정책](../../references/execution-policy.md)을 현재 문맥에 없을 때만 읽는다.
현재 호스트 문서와 [근거 중심 작업 절차](../../references/evidence-workflow.md)도 이미 확인한 내용은 재사용한다.
두 호스트 모두 역할 지침을 읽고 메인이 직접 수행한다. 독립 스펙·AST 분석만 필요할 때 위임한다.
Claude Agent 예시는 선택적 위임 형식이며 Codex의 전역 에이전트 설정으로 설치하지 않는다.
전체 소스·JSON을 역할마다 복제하지 않고 필요한 필드와 산출물 경로를 전달한다.

## 입력·호출 경계

사용자의 자연어 또는 HarnessRequest를 받는다. [데이터 계약](references/data-contracts.md)은 필드/결과 형식이 필요할 때만 읽는다.
기존 projectRoot, specDocPaths, targets/targetModules, coverage, springProfile, maxRepairRetries,
coverageMaxIterations, refactorAdvisory와 schemaVersion:2를 유지한다. executionPolicy는 선택이다.
확정된 절대 프로젝트 루트를 사용하고 모듈 root와 패키지/FQCN 대상을 섞지 않는다.
단순 조회는 산출물·신선도를 읽어 보고한다. 빌드·보정·승인을 새로 시작하지 않는다.

## 재개와 환경

1. 현재 요청이 새 작업인지, 명시적 계속인지, 같은 작업 자동 재개인지 구분한다.
2. 유효한 `_workspace/00_config-harness.json`과 실제 승인·생성 출처·실행 증거를 읽는다.
3. workspace가 불완전하면 `detect_pipeline_state(root=projectRoot, line=..., branch=..., method=..., klass=..., packages=targets, excludes=coverage.excludes)`를 호출한다. 설정 없는 경우 보수적 기존 도구 기본값을 사용한다.
4. `harnessProvenance:false`인 일반 기존 테스트는 덮어쓰지 않는다. staleness와 recommendedEntryStage보다 뒤로 건너뛰지 않는다. 안전한 영향 단계로 자동 재개하고 무엇을 재사용하는지 알린다. 재개 단계 자체를 매번 질문하지 않는다.
5. 승인/설계가 달라졌으면 영향 시나리오만 다시 승인받는다. `04b_approval.json`, `09_conformance.json`은 성공 stub으로 만들지 않는다.
6. legacy workspace 보존 이동 시 `.markers/`와 `execution-budget.json`/`.lock`은 남긴다. 자동 재개로 예산을 삭제하거나 0회로 초기화하지 않는다.

E-verify는 [environment-setup.md](../../references/environment-setup.md)의 해당 호스트 프로브를 세션/환경 변경 시 수행한다.
0단계 configure-harness가 프로브를 실행하면 오케스트레이터는 중복 실행하지 않는다. 재사용·재개 경로에서만 메인이 세션 단위 연결을 확인한다.
필요한 MCP의 연결 실패를 파일 눈대중/정규식 파서로 대체하지 않는다.
환경 누락 시 구체적인 준비 작업과 다운로드를 한 번 제시한다. 동의가 있으면 setup-harness가 수행하고 원래 요청으로 돌아온다.
동의·역량이 없으면 `먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요`와 실패 항목을 안내한다.
무동의 자동 세팅·자동 위임 금지. 세션 재시작이 필요하면 현재 대상·설정·재개 지점을 보존한다.

## 분석·설계·승인·생성

| 단계 | 사용할 역할/스킬 | 즉시 저장할 `_workspace/` 산출물 |
|---|---|---|
| 0 | configure-harness | 00_config-harness.json, 필요한 경우 00b_build_provision.json |
| 1 | spec-reviewer / ingest-specs | 01_spec-reviewer_criteria.json |
| 2 | ast-structure-analyzer / analyze-ast | 02_ast_targets.json |
| 3 | source-code-analyzer / analyze-source | 03_source_seams.json |
| 3.5 | refactor-advisor | 03b_refactor_advisory.json, 03c_advisory_gate.json |
| 4 | scenario-generator / generate-scenarios | 04_scenario_set.json |
| 4.5 | 메인 사용자 승인 | 04b_approval.json |
| 5 | test-code-generator / generate-tests | 05_test-gen_files.json |

- specDocPaths가 비면 실제 무스펙 상태와 출처 한계를 기록한다. 빈 스펙 때문에 불필요한 인제스트 역할을 띄우지 않는다.
- AST 메타와 대상·직접 협력 객체의 실제 소스로 동작을 확인한다. 확인하지 못한 심볼을 추측하지 않는다.
- 리팩토링 권고는 기록하고 대상을 기본 포함한다. 별도 포함/제외 질문을 하지 않고 시나리오 승인에 권고와 예상 비용을 함께 보여준다.
- 시나리오를 `test_docs/scenarios/<id>.md`에 pending으로 저장한 뒤 승인/수정/제외를 한 번 묻는다. 승인분만 생성한다. 명시적 CI 정책은 기록하며 질문 도구 부재·무응답을 자동 승인으로 해석하지 않는다.
- 범위 제외 결정을 03c와 04b에 반영한다. 승인 0건이면 partial로 종료한다. 제외가 coverage.excludes를 임의 변경하지는 않는다.
- 생성된 테스트의 scenarioRef/criteriaRef와 targetCallCheck를 확인한다. 기록→AST parse→target 호출 대조를 같은 역할에서 수행한다. 불일치 파일은 성공으로 반환하지 않는다.
- test-code-generator·coverage-closer·test-fixer·test-editor 역할은 직접 수행 또는 위임할 수 있다. 위임한 역할이 쓴 파일은 다시 Write하지 않는다.
- 테스트 불변식은 [test-code-invariants.md](../../references/test-code-invariants.md)를 적용한다. 별도 메타 테스트·중복 리뷰는 추가하지 않는다.

## 하나의 검증·보정 루프

초기 생성 후, 또는 영향 단계에서 재개할 때 다음 회차를 수행한다.

1. **6단계 테스트**: 승인된 생성 테스트와 gap 테스트를 포함한 정확한 범위를 `run_targeted_tests(with_coverage=true,reuse_if_fresh=true)`로 실행한다. config의 task, java_home, report_dirs/report_paths를 전달한다. 같은 실행의 runResult·testcases·coverageReportPaths·executionEvidence를 저장한다.
2. **8단계 커버리지**: 그 실행의 보고서로 `coverage_gate(require_fresh=true,...)`를 호출하고 counters/gaps를 `08_coverage_result.json`에 저장한다. 측정은 추가 보정을 의미하지 않는다. iterations:0인 정직한 미달 결과도 유효하다.
3. **9단계 적합성**: methodCallDetails로 수신자·target을 대조하고 judgment를 기록한다. NOT_EXECUTED는 불충족이다. 같은 실행의 메서드 결과와 승인 시나리오·target 호출·then 단언을 확인하고 `09_conformance.json`과 test_docs를 갱신한다. 실패/미실행 항목은 불충족이며 이전 보고서를 쓰지 않는다.
4. **판정**: 모두 충족하면 완료. 부족하면 실패 테스트 > 적합성 > 커버리지 순으로 다음 보정 한 묶음을 선택한다.
5. **예산**: 공용 budget reserve를 호출한다. 허용되지 않으면 잔여를 전량 보고하고 partial로 종료한다. 모드/종료 조건의 정본은 execution-policy.md다.
6. **수정**: 실패는 test-fixer(7단계), unsatisfied는 test-fixer 모드 B, missing은 해당 시나리오만 test-code-generator(9.5단계), gap은 coverage-closer로 수행한다. 역할을 직접 수행할 때도 같은 예약 ID를 사용한다. 다른 원인의 추가 수정은 새 예약이 필요하다.
7. **필수 재검증**: 각 라운드는 반드시 6→8→9 순서로 현재 증거를 갱신한 뒤 budget complete한다. 실행 자체가 불가하면 실제 실패와 blocked 단계를 기록하고 complete한다. 이후 4번으로 간다.

빌드 실패·XML 부재라 8/9를 수행할 수 없으면 blocked/failed와 이유를 남긴다. 과거 green 보고서로 채우지 않는다.
마지막 측정 실행이 생성+추가 테스트 전체를 포함하면 그것을 최종 runResult로 사용한다. 별도 “회귀 실행”은 하지 않는다.
실행 범위가 불완전하면 합친 범위로 한 번 실행한 결과를 최종 검사한다. 범위 밖 코드를 임의 제외해 통과시키지 않는다.
현재 runResult.testcases가 있으면 같은 JUnit XML을 다시 파싱하지 않는다. 누락됐을 때만 parse_junit_xml로 보완한다.
수정 없는 조회/검증 요청은 이 보정 루프에 진입하지 않는다.

## 결과

schemaVersion:2 PipelineResult와 `pipeline_result.json`을 기록한다. 각 단계는 실제 ok/partial/failed 또는 blocked/skipped를 구분한다.
승인·현재 JUnit(passed>0, 실패 없음)·선택 임계값 JaCoCo·승인 시나리오 전부 satisfied일 때만 전체 ok다.
최종 stages.verifyScenarios의 approved/satisfied/unsatisfied/missing을 09 totals와 일치시킨다.
executionSummary에는 공용 budget status의 profile/maxAutoFixRounds/autoFixRounds/stopReason와 실제 재사용 근거를 넣는다.
`test_docs/INDEX.md`에는 시나리오↔테스트↔결과와 잔여·권고 링크를 남긴다. 최종 채팅은 핵심 수치·미해결 항목·파일 경로만 보여준다.
성능 수치는 실제 관측만 기록하고 토큰 수를 추정하지 않는다.

## 조건부 참조

- 부분 재실행 매핑·영속 복원: [orchestration-detail.md](references/orchestration-detail.md)
- 버전/API가 달라진 경우: [version-compatibility.md](../../references/version-compatibility.md), [compatibility-runtime.md](../../references/compatibility-runtime.md)
- 오류가 생긴 경우: [fallback-policy.md](../../references/fallback-policy.md)
- 시나리오 문서 형식: [scenario-docs.md](../../references/scenario-docs.md)

Claude의 guard-gate-artifacts는 활성 세션에서 승인·순서·결과를 검사한다. spawn 강제는 없다.
