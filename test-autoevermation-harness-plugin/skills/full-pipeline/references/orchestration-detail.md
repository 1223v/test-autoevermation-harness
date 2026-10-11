# 재개·산출물 상세

기본 실행과 예산은 [full-pipeline](../SKILL.md), [execution-policy](../../../references/execution-policy.md)가 정본이다. 이 문서는 재개 시에만 읽는다.
메인이 직접 수행하며 독립 스펙·AST 분석만 선택적으로 위임한다. 전체 JSON·소스 대신 대상·필요 필드·산출물 경로를 전달한다.

## 2. `_workspace/` 규약

```text
_workspace/
├── 00_config-harness.json
├── 00b_build_provision.json
├── 01_spec-reviewer_criteria.json
├── 02_ast_targets.json
├── 03_source_seams.json
├── 03b_refactor_advisory.json
├── 03c_advisory_gate.json
├── 04_scenario_set.json
├── 04b_approval.json
├── 05_test-gen_files.json
├── 06_run_result.json
├── 07_repair_result.json
├── 08_coverage_result.json
├── 09_conformance.json
├── 09b_conformance_repair.json
├── _resume.json
├── timing.json
└── pipeline_result.json
```

- 최종 테스트는 `src/test/java`, 시나리오 문서는 `test_docs/`에 쓴다.
- 중간 JSON은 `_workspace/`에만 두고, 메인 컨텍스트에는 `{status, 핵심수치, 경로}`만 환원한다.
- `00_config-harness.json`, `_resume.json`, `pipeline_result.json`은 `schemaVersion:2`가 필수다.
- 버전이 없거나 2가 아닌 workspace는 `_workspace_legacy_{YYYYMMDD_HHMMSS}/`를 만들고 `.markers/`, `execution-budget.json`, `execution-budget.lock`을 제외한 항목만 보존 이동한다. 현재 세션의 `_workspace/.markers/run.json`은 훅의 물리 가드이므로 원래 위치에 유지하고, 구 산출물을 새 workspace에 복사하지 않는다.

### 2-1. 영속 증거 복원

`detect_pipeline_state` 결과는 `harnessProvenance:true`일 때만 stub으로 복원한다. 모든 stub에는 `source:"durable-scan"`을 넣고, 훅이 **실제 요청 root·임계값과 도구 응답에서 해당 파일을 `allowedArtifacts`로 기록한** 대상 `projectRoot`의 detect 마커가 있어야 한다. 08 권한은 호출 임계값이 schema v2 config와 일치할 때만 생기며(config가 없으면 네 값 모두 1.0), stub은 `status:"reused"`, `gatePassed:true`가 필수다. 아래 표의 네 산출물만 복원할 수 있으며 `04b_approval.json`과 `09_conformance.json`은 stub으로 만들지 않는다. 여기서 **green JUnit**은 파서 결과가 `status:"ok"`, `passed>0`, `failed=[]`인 경우만 뜻하며 테스트가 0개인 XML은 green이 아니다.

| 영속 증거 | 복원 stub | 추천 재진입 |
|---|---|---|
| 승인 시나리오만 존재 | `04_scenario_set.json` | 5 generate-tests |
| 하네스 테스트 존재, JUnit 없음·실패·partial | `05_test-gen_files.json` | 6 run-tests |
| green JUnit 존재, JaCoCo 없음·현재 임계 미달 | `06_run_result.json` | 8 measure-coverage |
| green JUnit + 현재 임계 통과 JaCoCo XML | `08_coverage_result.json` | 9 verify-scenarios |
| 영속 증거 없음 | 없음 | 0 configure-harness |

손수 작성한 기존 테스트만 있는 경우에는 stub을 만들지 않는다. 초기 실행하되 파일을 덮어쓰지 않고 `existingTestPaths`로 전달한다.

`_resume.json`:

```json
{
  "schemaVersion": 2,
  "entryStage": 8,
  "entryLabel": "stage 8: measure-coverage",
  "ts": "<ISO-8601>"
}
```

- statusline은 schema v2 resume만 읽고 재진입 단계보다 뒤의 표시를 차단한다.
- `pipeline_result.json`도 schema v2일 때만 완료로 표시한다.
- 복원은 완료가 아니므로 최종 집계 전에는 `pipeline_result.json`을 기록하지 않는다.

## 3. 부분 재실행

| 요청 | 경로 |
|---|---|
| 결과 조회 | 기존 결과·신선도만 보고, 빌드 없음 |
| 테스트 실행 | 6만 실행, 자동 수정 없음 |
| 커버리지 측정 | 유효 실행 재사용 또는 한 번 실행 → 8, 자동 수정 없음 |
| 적합성 확인 | 9만 확인, 미실행은 미검증 |
| 스펙·대상 변경 후 생성 | 변경된 분석 → 4 → 4.5 승인 → 5 → 6→8→9 |
| 실패·적합성·커버리지 개선 | 현재 증거 평가 → 예산 예약 → 해당 수정 → 6→8→9 |
| 목표값 변경 | 명시적인 설정 변경 → 유효 보고서 평가; 추가 수정은 요청 범위 안에서 |

자동 재개는 예산 파일을 유지한다. 예산이 사라졌고 이전 보정 이력이 있으면 중단하고 복원/새 예산 승인을 요청한다.
최종 실행이 전체 승인 대상과 추가 테스트를 포함하면 별도 회귀 실행은 없다.

## 4. 시간 기록

실제 관측값만 timing.json에 기록한다. 선택 위임에 대한 SubagentStart/Stop 시간은 전체 직접 수행 시간이 아니다.
토큰 정보가 없으면 필드를 생략한다. 직접 수행 시간이나 토큰을 spawn 시간으로 추정하지 않는다.
