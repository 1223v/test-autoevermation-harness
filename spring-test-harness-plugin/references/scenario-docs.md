# 시나리오 문서·승인·적합성 검증 (SSOT)

이 문서는 하네스의 **시나리오 산출물(`test_docs/`)·사용자 승인 게이트·시나리오 적합성(conformance) 검증**에 대한
단일 출처(Single Source of Truth)다. `full-pipeline`·`generate-scenarios`·`verify-scenarios` 스킬과
`scenario-conformance-verifier` 에이전트는 이 문서를 따른다.

설계 근거(웹 검증 2026-06-27): BDD/Living Documentation는 **테스트 스위트에서 생성되어 항상 최신인 실행 가능 명세**이며,
요구사항을 **안정적 ID로 테스트에 묶어 추적성**을 제공한다. 본 하네스는 이미 ① 시나리오를 BDD given/when/then으로
구조화하고 ② 테스트 메서드명에 `scenarioRef`(`SC-001`→`sc001_…`)를, javadoc에 `criteriaRef`/`scenarioRef`를 기록한다.
`test_docs/`는 이 추적성을 사람이 읽는 **living documentation**으로 외부화한 것이다.
출처: Serenity BDD Living Documentation, Cucumber "How does BDD affect traceability", JUnit 5 `@DisplayName`(리포팅 추적성).

---

## 1. 핵심 원칙

1. **시나리오는 사용자 승인을 받는다.** 시나리오 설계(4단계) 직후, 테스트 코드 생성(5단계) **전에** 사용자 승인 게이트를 둔다.
   - 대화형 CLI: `AskUserQuestion`으로 승인/제외·수정/재설계를 묻는다. **승인된 시나리오만** 테스트 생성으로 넘어간다.
   - 비대화형·CI(`claude -p`): 승인할 사람이 없으므로 **자동 승인**하고 `test_docs/`에 그대로 기록(감사 추적) 후 진행한다.
     (승인 게이트는 본질적으로 대화형 전용이다. fallback-policy.md #15.)
2. **시나리오는 대상 프로젝트의 `test_docs/`에 `.md`로 저장한다.** 시나리오별 파일 + 인덱스 구조.
   `test_docs/`는 플러그인 저장소가 아니라 **분석 대상 프로젝트 루트**(`projectRoot`) 아래에 만든다.
3. **모든 과정(생성·실행·커버리지·뮤테이션)이 끝나면 시나리오 적합성을 검증한다.** 생성·통과한 테스트가
   각 (승인된) 시나리오의 given/when/then을 **실제로 만족**하는지 확인한다(단순 통과 여부가 아니라 시나리오 충족 여부).
4. **결과를 `test_docs/`에 시나리오 ↔ 테스트코드 ↔ 결과로 정리한다.** 각 시나리오 파일과 인덱스에 매핑·검증 결과를 기록한다.

---

## 2. `test_docs/` 디렉터리 구조

```
<projectRoot>/test_docs/
├── INDEX.md                  # 시나리오↔테스트코드↔결과 매핑 표 + 요약
└── scenarios/
    ├── SC-001.md             # 시나리오 1건 = 파일 1개
    ├── SC-002.md
    └── ...
```

규칙:
- 파일명은 시나리오 `id`(`SC-001.md`). 안정적 ID라 재실행 시 같은 파일을 갱신(전량 재작성 금지, 변경분만).
- `test_docs/`는 **사람이 읽는 산출물**이므로 대상 프로젝트에 커밋될 수 있다(`_workspace/`와 달리 ignore 대상 아님).
- 소스 원문·민감정보(토큰·접속문자열)는 기록하지 않는다(시나리오 설명·단언 수준만).

### 2.1 시나리오 파일 템플릿 (`scenarios/<id>.md`)

```markdown
---
scenarioId: SC-001
title: 재고 부족 시 주문 생성 실패
type: unit            # unit | slice | integration
target: com.example.order.OrderService#createOrder
priority: P0
criteriaRefs: [AC-001]
approval: approved    # pending | approved | excluded
approvedAt: 2026-06-27
---

# SC-001 — 재고 부족 시 주문 생성 실패

## 시나리오 (BDD)
- **Given**: 재고가 0인 상품 / 주문 수량 1
- **When**: createOrder(상품, 수량) 호출
- **Then**: OutOfStockException 발생 / 주문이 저장되지 않음

## 추적성
- acceptance criteria: AC-001
- testSeam / mock: OrderRepository (mock 대상)
- slice/통합 사유: —   (integration일 때 slowReason 기재)

## 테스트 코드 매핑      <!-- 5단계(생성) 후 채움 -->
- 파일: `src/test/java/com/example/order/OrderServiceTest.java`
- 메서드: `sc001_재고부족시_주문생성_실패()`

## 검증 결과            <!-- 10단계(적합성 검증) 후 채움 -->
- 적합성: ✅ satisfied        (satisfied | unsatisfied | missing)
- 실행: passed               (passed | failed | not-run)
- then 단언 커버: 2/2
- 비고: —
```

미채움 섹션은 해당 단계 전까지 `<!-- 대기 -->`로 둔다.

### 2.2 인덱스 템플릿 (`INDEX.md`)

```markdown
# 테스트 시나리오 인덱스 (living documentation)

> 생성: 2026-06-27 14:00 · 프로젝트: `/path/to/project` · 하네스 v0.7.0

## 요약
- 시나리오: 8 (승인 7 / 제외 1)
- 테스트 매핑: 7/7 (승인분)
- 적합성: satisfied 6 / unsatisfied 1 / missing 0

## 시나리오 ↔ 테스트코드 ↔ 결과
| 시나리오 | 유형 | 대상 | 승인 | 테스트코드 | 실행 | 적합성 | criteria |
|---|---|---|---|---|---|---|---|
| [SC-001](scenarios/SC-001.md) | unit | OrderService#createOrder | ✅ | `OrderServiceTest#sc001_…` | ✅ | ✅ | AC-001 |
| [SC-002](scenarios/SC-002.md) | slice | OrderController#create | ✅ | `OrderControllerTest#sc002_…` | ✅ | ⚠️ | AC-002 |
| [SC-007](scenarios/SC-007.md) | integration | … | ⛔ 제외 | — | — | — | AC-009 |

범례: 승인 ✅승인/⛔제외 · 실행 ✅통과/❌실패/—미실행 · 적합성 ✅satisfied/⚠️unsatisfied/⛔missing
```

---

## 3. 승인 게이트 (4.5단계)

`generate-scenarios`(4단계)가 `ScenarioSet`을 반환한 직후:

1. **선(先) 기록**: 각 시나리오를 `test_docs/scenarios/<id>.md`(approval: `pending`)로 쓰고 `INDEX.md`를 갱신한다.
2. **승인 게이트**:
   - **대화형**: 시나리오 요약(유형별 개수·목록)을 제시하고 `AskUserQuestion`으로 묻는다 —
     선택지 `전체 승인` / `일부 제외·수정` / `재설계 요청`.
     - `일부 제외·수정`: 후속 질문 또는 자유 입력으로 제외/수정할 시나리오 `id`를 받는다. 제외분은 `approval: excluded`.
     - `재설계 요청`: 사유를 받아 4단계(generate-scenarios)를 재호출한다(부분 재실행).
   - **비대화형·CI**: 전체 `approved`로 자동 승인하고 진행(기록만 남김).
3. **반영**: 승인분만 `approval: approved`로 갱신하고, **승인된 시나리오 집합만** 5단계(generate-tests) 입력으로 넘긴다.
   제외분은 `excluded`로 남겨 추적성을 유지한다(파일 삭제 금지).

게이트: 대화형에서 사용자가 `재설계`를 반복 선택하면 4↔4.5를 재실행한다(무진전 판정은 fallback-policy.md #12 준용).

---

## 4. 적합성 검증 (10단계 — 마지막)

커버리지 게이트(8단계)·뮤테이션 강화(9단계)까지 끝난 뒤, `verify-scenarios` 스킬이
`scenario-conformance-verifier` 에이전트로 **승인된 각 시나리오가 실제로 충족되었는지** 검증한다.

검증 절차(시나리오 1건당):
1. **매핑**: `scenarioRef`(메서드명 `sc001_…`)와 javadoc `scenarioRef/criteriaRef`로 시나리오 → 테스트 메서드를 찾는다.
   매핑되는 메서드가 없으면 `missing`.
2. **실행 결과**: 매핑된 메서드가 최종 실행에서 `passed`인지 확인한다. `failed`/미실행이면 `unsatisfied`.
3. **then 충족**: 테스트 본문의 `// then` 단언이 시나리오 `then` 항목을 **빠짐없이** 반영하는지 확인한다
   (단언 누락·약화 시 `unsatisfied`, 사유 기록). given/when도 시나리오와 일치하는지 점검한다.
4. **판정**: `satisfied`(매핑+통과+then 충족) / `unsatisfied`(매핑되나 실패·단언 부족) / `missing`(매핑 테스트 없음).

산출 후:
- 각 `scenarios/<id>.md`의 "테스트 코드 매핑"·"검증 결과" 섹션을 채우고 `INDEX.md`를 갱신한다.
- `ConformanceResult` JSON을 반환한다(아래 스키마).

### 4.1 게이트 (fallback-policy.md #16)

- `missing` 또는 `unsatisfied` 시나리오가 하나라도 있으면 파이프라인 `status: "partial"`로 보고하고 잔여를 전량 명시한다.
- 전부 `satisfied`라야 `status: "ok"`. 임의 제외·무시 금지(커버리지/뮤테이션 게이트와 동일 정책).
- 대화형: 잔여 unsatisfied/missing에 대해 `AskUserQuestion`("추가 보정 시도 / partial로 종료")로 후속을 정할 수 있다.
  보정 시도 선택 시 5→6→(8·9) 부분 재실행. CI: `partial`로 보고 후 종료.

### 4.2 `ConformanceResult` 스키마

```json
{
  "status": "ok | partial | failed",
  "summary": "승인 7건 중 satisfied 6 / unsatisfied 1 / missing 0",
  "totals": { "approved": 7, "satisfied": 6, "unsatisfied": 1, "missing": 0 },
  "scenarioResults": [
    {
      "scenarioId": "SC-001",
      "testClass": "com.example.order.OrderServiceTest",
      "testMethods": ["sc001_재고부족시_주문생성_실패"],
      "mapped": true,
      "executed": "passed",
      "thenCovered": "2/2",
      "verdict": "satisfied",
      "notes": ""
    }
  ],
  "unmet": ["SC-002"],
  "docPaths": ["test_docs/INDEX.md", "test_docs/scenarios/SC-001.md"],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

---

## 5. `_workspace/`·부분 재실행 연계

- `04_scenario_set.json`(설계) → `04b_approval.json`(승인/제외 결과) → … → `10_conformance.json`(적합성).
- 승인 결과(`04b_approval.json`)는 5단계 입력 필터로 쓰고, 부분 재실행("이 패키지만", "시나리오 다시")에서 재사용한다.
- `test_docs/`는 대상 프로젝트의 영속 산출물, `_workspace/*.json`은 감사용 중간 산출물(서로 다른 위치).
