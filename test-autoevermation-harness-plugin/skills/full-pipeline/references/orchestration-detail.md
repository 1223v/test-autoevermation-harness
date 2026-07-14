# full-pipeline 오케스트레이션 상세

> `full-pipeline/SKILL.md`의 실행 모드, workspace, 부분 재실행 규약을 보충한다.

## 1. 실행 모드

| 구간 | 모드 | 이유 |
|---|---|---|
| 1·2단계 | `Task` 병렬 팬아웃 | 스펙과 AST 분석은 서로 독립적 |
| 3~9단계 | 순차 서브에이전트 파이프라인 | 이전 단계 산출물에 의존 |
| 보정·커버리지 루프 | 생성-검증 반복 | 결정적 무진전 신호로 종료 가능 |

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
- 버전이 없거나 2가 아닌 workspace는 `_workspace_legacy_{YYYYMMDD_HHMMSS}/`를 만들고 `.markers/`를 제외한 항목만 보존 이동한다. 현재 세션의 `_workspace/.markers/run.json`은 훅의 물리 가드이므로 원래 위치에 유지하고, 구 산출물을 새 workspace에 복사하지 않는다.

### 2-1. 영속 증거 복원

`detect_pipeline_state` 결과는 `harnessProvenance:true`일 때만 stub으로 복원한다. 모든 stub에는 `source:"durable-scan"`을 넣고, 훅이 남긴 detect 마커가 있어야 한다. 아래 표의 네 산출물만 복원할 수 있으며 `09_conformance.json`은 매번 다시 실행한다.

| 영속 증거 | 복원 stub | 추천 재진입 |
|---|---|---|
| 승인 시나리오만 존재 | `04_scenario_set.json`, `04b_approval.json` | 5 generate-tests |
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

## 3. 부분 재실행 매트릭스

| 사용자 요청 | 재실행 단계 | 재사용 |
|---|---|---|
| 특정 패키지·클래스만 다시 | 2→3→3.5→4→4.5→5→6→8→9 | 01 |
| 스펙 추가 | 1→4→4.5→5→6→8→9 | 02·03·03b·03c |
| 리팩토링 권고 다시 | 3.5→4→4.5→5→6→8→9 | 01~03 |
| 시나리오·승인 다시 | 4→4.5→5→6→8→9 | 01~03·03b·03c |
| 커버리지 더 올리기 | 8→9 | 01~06·04b |
| 테스트 실패 보정 | 7→6→8→9 | 01~05·04b |
| 임계값 변경 | 0→8→9 | 01~06·04b |
| 적합성만 확인 | 9, 필요 시 9.5 | 01~08·04b |
| 적합성 불일치 보정 | 9.5→6→8→9 | 01~08·04b·09_conformance |

이전 산출물 경로를 하위 프롬프트에 전달하고 변경분만 반영한다. 전량 재생성하지 않는다.

## 4. 데이터 전달

| 전략 | 적용 |
|---|---|
| `_workspace/*.json` 경로 전달 | 구조화된 전체 산출물 |
| `Task` 반환 요약 | 병렬 단계 상태·수치 |
| `{status, 수치, 경로}` 환원 | 메인 컨텍스트 절약 |

## 5. `timing.json`

서브에이전트 완료 알림 시점에 `total_tokens`와 `duration_ms`를 즉시 기록한다.

```json
{
  "stages": [
    {
      "stage": "02_ast",
      "agent": "ast-structure-analyzer",
      "model": "inherit",
      "total_tokens": 63505,
      "duration_ms": 444344
    }
  ],
  "totals": {
    "total_tokens": 63505,
    "duration_ms": 444344,
    "total_duration_seconds": 444.344
  }
}
```

## 6. 에러 처리

| 상황 | 처리 |
|---|---|
| repair 가능한 실패 | 진전이 있는 동안 재시도 |
| 동일 실패 시그니처 3회 | `partial`과 잔여 전체 보고 |
| 동일 미커버 집합 3회 | `partial`과 `remainingGaps[]` 전체 보고 |
| 1·2단계 모두 실패 | 중단 |
| AST 실패 | 중단 |
| 상충 데이터 | 삭제하지 않고 출처 병기 |
| 9.5 적합성 보정 | 최대 3라운드, 동일 unmet 즉시 중단 |
| 무효 커버리지 산출물 | guard가 기록 차단 후 8단계 재실행 |

`maxIterations`와 `maxRepairRetries`는 무진전 감지를 위한 추적 단위다. 진전이 있으면 계속하고, 본문 `full-pipeline/SKILL.md`의 실패 처리 규약을 정본으로 삼는다.
