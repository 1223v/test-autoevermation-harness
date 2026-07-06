# full-pipeline 오케스트레이션 상세

> 본문(SKILL.md)에서 "실행 모드 · _workspace · 부분 재실행" 절의 상세 레퍼런스. 필요할 때만 로드한다.
> 설계 근거: revfactory/harness `references/orchestrator-template.md`(Phase 0, §5-1 데이터 전달, §5-2 에러), `references/skill-testing-guide.md` §3-3(타이밍 캡처).

## 목차
1. 실행 모드 선택 근거
2. `_workspace/` 디렉터리 규약
3. 부분 재실행 매트릭스
4. 단계 간 데이터 전달 표
5. timing.json 계측 스키마
6. 에러 핸들링

---

## 1. 실행 모드 선택 근거

| 구간 | 모드 | 이유 |
|---|---|---|
| 1·2단계(ingest-specs ∥ analyze-ast) | 서브에이전트 팬아웃 (`Task`, 병렬) | 상호 통신 불필요한 독립 작업. 에이전트 팀의 조율/브로드캐스트 토큰·지연 비용이 이득보다 큼 |
| 3~9단계 | 서브에이전트 파이프라인 (순차) | 이전 단계 산출물에 강하게 의존 |
| 보정·커버리지·뮤테이션 루프 | 생성-검증(producer-reviewer) | 최대 반복 한도로 무한루프 방지 |

> 참고 하네스의 의사결정 트리("팀 통신이 정말 불필요한가?")를 통과 → 서브에이전트가 올바른 선택. 팀 모드는 팀원 간 실시간 토론이 품질을 좌우할 때만 채택한다(본 파이프라인은 해당 없음).

---

## 2. `_workspace/` 디렉터리 규약

작업 루트 하위에 중간 산출물을 보존한다. 파일명: `{단계번호}_{에이전트}_{산출물}.json`.

```
_workspace/
├── 00_config-harness.json              # configure-harness 결과(HarnessConfig)
├── 00b_build_provision.json             # 0.6단계 빌드 능력 감지/주입·캐시 프라이밍 결과(buildChanges 포함)
├── 01_spec-reviewer_criteria.json
├── 02_ast_targets.json
├── 03_source_seams.json
├── 03b_refactor_advisory.json           # 3.5단계 refactor-advisor 판정(RefactorAdvisoryResult)
├── 03c_advisory_gate.json               # 3.5단계 포함/제외 결정 → 4단계 입력 필터
├── 04_scenario_set.json
├── 04b_approval.json                    # 승인/제외 결과(승인 게이트) → 5단계 입력 필터
├── 05_test-gen_files.json               # 생성 파일 경로 목록
├── 06_run_result.json
├── 07_repair_result.json                # 실패 시에만
├── 08_coverage_result.json
├── 09_mutation_result.json
├── 10_conformance.json                  # 시나리오 적합성 검증 결과
├── 10b_conformance_repair.json          # 10.5단계 적합성 자동 보정 라운드 로그(unmet 존재 시에만)
├── timing.json                          # 단계별 토큰/시간 누적
└── pipeline_result.json                 # 최종 집계
```

규칙:
- 최종 산출물(생성된 테스트 파일)은 프로젝트의 `src/test/java`에, **시나리오 living documentation**(`test_docs/scenarios/*.md`·`INDEX.md`)은 프로젝트의 `test_docs/`에 쓴다. 중간 JSON은 `_workspace/`에 보존(사후 검증·감사 추적).
- 메인 컨텍스트에는 각 단계의 `{status, 핵심수치, 경로}`만 환원한다. 대용량 배열(시나리오·uncovered·survivor 목록)은 파일에만 둔다.
- `.gitignore`에 `_workspace/` 추가(운영 산출물). **`test_docs/`는 사람이 읽는 영속 산출물이므로 ignore 대상이 아니다**(대상 프로젝트에 커밋 가능).

---

## 3. 부분 재실행 매트릭스

Phase 0에서 요청 유형을 분류해 영향 단계만 재실행한다. 나머지는 `_workspace/`의 기존 JSON을 Read로 재사용.

| 사용자 요청 유형 | 재실행 단계 | 재사용(Read) |
|---|---|---|
| "이 패키지/클래스만 다시" | 2(ast)→3→3.5(권고 게이트)→4→4.5→5→6→8→(9)→10 (대상 스코프 한정) | 01_spec |
| "스펙 문서 추가했어" | 1(spec)→4→4.5→5→6→8→(9)→10 | 02_ast, 03_source, 03b·03c(권고 필터) |
| "리팩토링 권고만 다시" | 3.5(판정+게이트)→4→4.5→5→6→8→(9)→10 | 01~03 |
| "시나리오 다시/승인 다시" | 4(scenario)→4.5(승인)→5→6→8→(9)→10 | 01~03, 03b·03c |
| "커버리지만 더 올려" | 8(measure-coverage 루프)→10 | 01~06, 04b |
| "뮤테이션만 다시" | 9(mutation-test 루프)→10 | 01~08, 04b |
| "테스트 실패 고쳐" | 7(repair)→6(재실행)→10 | 01~05, 04b |
| "임계값 바꿔서 다시" | configure(0)→8→9→10 | 01~06, 04b |
| "시나리오 만족하는지만 확인" | 10(verify-scenarios) — unmet이면 10.5 자동 보정 루프 진입 | 01~09, 04b |
| "시나리오 적합성 불일치 고쳐" | 10.5(unsatisfied→fixer 모드 B / missing→부분 재생성)→6→10 (테스트 변경 시 8·9 회귀) | 01~09, 04b, 10_conformance |

부분 재실행 시 해당 에이전트 프롬프트에 **이전 산출물 경로**를 전달해 "기존 결과를 읽고 변경분만 반영"하도록 지시한다(전량 재생성 금지).

---

## 4. 단계 간 데이터 전달 표

| 전략 | 방식 | 적용 | 적합 |
|---|---|---|---|
| 파일 기반 | `_workspace/*.json` 경로 전달 | 전 단계 | 대용량 구조화 산출물(기본) |
| 반환값 기반 | `Task` 반환 요약 | 1·2단계 병렬 수집 | 짧은 상태/수치 |
| 요약 환원 | `{status,수치,경로}`만 메인에 | 전 단계 | 컨텍스트 절약 |

권장 조합: **파일 기반(산출물) + 반환값 요약(조율)**. 대용량 목록은 절대 메인 컨텍스트로 통째 전달하지 않는다.

---

## 5. timing.json 계측 스키마

각 서브에이전트 **완료 알림 시점**에만 `total_tokens`/`duration_ms`를 얻을 수 있다(이후 복구 불가). 즉시 누적 저장한다.

```json
{
  "stages": [
    {"stage": "02_ast", "agent": "ast-structure-analyzer", "model": "inherit",
     "total_tokens": 63505, "duration_ms": 444344}
  ],
  "totals": {"total_tokens": 0, "duration_ms": 0, "total_duration_seconds": 0.0},
  "slowest": "02_ast",
  "most_expensive": "05_test-gen"
}
```

헬퍼 `scripts/record-timing.py`로 한 줄씩 append + totals/slowest 재계산. 이 데이터로 단계별 병목(느린/비싼 단계)을 식별해 모델 티어·스코프를 조정한다.

---

## 6. 에러 핸들링

정책: [references/fallback-policy.md](../../../references/fallback-policy.md) #12 — **성공까지 재시도 + 무진전 시 중단**.

| 상황 | 전략 |
|---|---|
| 단계 실패(repair 가능) | **게이트 충족까지 재시도**(고정 횟수 제한 없음). 진전이 있는 한 계속 |
| **무진전 판정** | 직전 반복과 비교해 (a) 동일 실패 시그니처 / (b) 동일 미커버 라인·브랜치 / (c) 동일 survivor 집합이 **3회 연속**이면 무진전 → `partial` + 잔여 전량 보고 후 중단 |
| 1·2단계 모두 실패 | 중단, `status: failed` |
| 2단계(ast) 실패 | 중단(AST 없이 이후 불가) |
| 상충 데이터 | 삭제하지 않고 출처 병기 |
| 커버리지/뮤테이션 미수렴 | 진전이 있으면 계속 재시도; **무진전 3회 연속**이면 `partial` + 잔여 gap/survivor 전량 보고(임의 제외/무시 금지) |
| 10.5단계 적합성 보정 루프 | **#12의 명시적 예외(#16)**: 적합성 판정은 일부 LLM 판단이라 무제한 재시도가 진동할 수 있음 → **최대 3라운드 하드 캡** + 직전 라운드와 동일 unmet 집합이면 즉시 무진전 중단. 소진 후 잔여는 대화형=질문 / CI=`partial` |
| 무효 게이트 산출물 (#21) | `08_coverage_result.json`이 `gatePassed:false`∧(`iterations<1`∨`remainingGaps` 빈 배열), 또는 `09_mutation_result.json`이 `thresholdMet:false`∧(`iterations<1`∨`survivingMutants` 빈 배열)이면 **게이트 미수행으로 무효** — 다음 단계 진행 금지, 해당 단계 재실행. RA advisory는 스킵 사유가 아님. `guard-gate-artifacts.py` 훅이 무효 산출물 Write를 차단 |

> `maxIterations`/`maxRepairRetries`는 **무진전 감지의 상한이 아니라 진전 추적 단위**로만 쓴다. 진전이 있는 한 상한에 도달해도 계속한다. 본문 "실패 처리 및 중단 조건" 표와 일관. 차이가 생기면 본문을 정본으로 한다.
