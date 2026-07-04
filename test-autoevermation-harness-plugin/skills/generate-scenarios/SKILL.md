---
name: generate-scenarios
description: AST 분석·소스 분석·스펙 결과를 수렴해 unit/slice/integration 테스트 시나리오를 설계한다. "테스트 시나리오", "시나리오 설계", "테스트 케이스 도출"처럼 시나리오 계획이 필요한 상황에서 자동 호출된다.
---

## 목적

`ingest-specs`의 acceptance criteria, `analyze-ast`의 testTargets, `analyze-source`의 testSeams·collaborators를 수렴해 최소 중복의 테스트 시나리오 집합을 설계한다. unit → slice → integration 순으로 우선순위를 부여하고, 중복 시나리오는 병합하며, 느린 시나리오(integration)는 사유를 명시한다.

> **승인 게이트 선행(다운스트림)**: 이 스킬의 출력(`ScenarioSet`)은 `generate-tests`로 바로 가지 않는다. `full-pipeline` 4.5단계에서 각 시나리오가 대상 프로젝트의 `test_docs/scenarios/<id>.md`로 저장되고 **사용자 승인 게이트**를 거친다(대화형=`AskUserQuestion`, CI=자동 승인). **승인된 시나리오만** 테스트 생성으로 넘어가고, 파이프라인 마지막에 적합성 검증(`verify-scenarios`)으로 시나리오 충족 여부가 확인된다. 정본: [references/scenario-docs.md](../../references/scenario-docs.md). 본 스킬 자체는 read-only이므로 `test_docs/` 저장·승인은 호출자(full-pipeline)가 수행한다.

---

## 자동 호출 조건

- 사용자가 "테스트 시나리오", "시나리오 설계", "테스트 케이스 도출", "AC 매핑"과 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 4단계(AST + 소스 + 스펙 결과 수렴 후)에서 순차 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:generate-scenarios
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `astResult` | `AstAnalysisResult` | 아니오 | `null` | `analyze-ast` 출력 |
| `sourceResult` | `SourceAnalysisResult` | 아니오 | `null` | `analyze-source` 출력 |
| `specResult` | `SpecReviewResult` | 아니오 | `null` | `ingest-specs` 출력 |
| `testScope` | `string` | 아니오 | `"mixed"` | `unit`/`slice`/`integration`/`mixed`. `unit`이면 unit 시나리오만 설계 (`HarnessRequest.testScope`) |

세 결과 모두 `null`이면 `status: "failed"`를 즉시 반환하고 선행 단계 실행을 안내한다. 일부만 있으면 `status: "partial"`로 진행한다.

> `full-pipeline`에서 호출될 때 `astResult`·`sourceResult`는 **3.5단계 리팩토링 권고 게이트에서 제외 대상이 이미 필터링된 버전**이다(정본: [refactor-advisory.md](../../references/refactor-advisory.md) §4). 이 스킬은 필터링을 재수행하지 않는다.

---

## 단계별 절차

1. **입력 검증**
   - 세 결과가 모두 없으면 `status: "failed"`, `errors: ["선행 단계(ingest-specs, analyze-ast, analyze-source) 실행 필요"]` 반환.
   - 일부 결과 누락 시 `status: "partial"`로 진행하고 누락 항목을 `warnings`에 기록.

2. **subagent 호출**

   ```
   Task(
     subagent_type="scenario-generator",
     model="inherit",
     prompt="""
   다음 세 가지 분석 결과를 수렴해 테스트 시나리오를 설계하라.

   입력:
   {
     "astResult": <astResult>,
     "sourceResult": <sourceResult>,
     "specResult": <specResult>,
     "testScope": <testScope>
   }

   지시:
   - spec-doc-mcp의 `search_requirements`와 repo-ast-mcp의 `extract_test_targets`를 보조로 활용할 수 있다.
   - acceptance criteria(criteriaRefs)와 testSeams를 매핑해 최소 시나리오 집합을 만들라.
   - testScope가 unit/slice/integration이면 해당 유형만 설계하고, mixed면 전체 유형을 허용하라.
   - **각 시나리오를 BDD Given/When/Then으로 구조화하라**: `given`(전제/입력 상태 배열), `when`(검증 대상 단일 행위), `then`(기대 결과/단언 배열)을 필수로 채운다. 한 시나리오의 `when`은 단일 행위로 유지(복합 행위는 별도 시나리오로 분리).
   - 시나리오 유형 우선순위: unit(P0 우선) → slice(P1) → integration(P2, 사유 명시 필수).
   - 동치류/경계값이 3개 이상인 경우 ParameterizedTest 시나리오로 표기하라.
   - 중복 시나리오는 병합하고 병합 사유를 summary에 기록하라.
   - 컨트롤러 → @WebMvcTest 슬라이스, JPA 레포 → @DataJpaTest 슬라이스, 서비스/순수 로직 → 순수 단위 테스트, 다계층 통합 → @SpringBootTest(최소화).
   - flaky 원인(sleep, broad catch, 실제 네트워크)이 포함될 수 있는 시나리오는 riskPoints에 기록하라.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "scenarios": [
       {
         "id": string,
         "title": string,
         "type": "unit" | "slice" | "integration",
         "target": string,
         "priority": "P0" | "P1" | "P2",
         "given": [string],
         "when": string,
         "then": [string],
         "criteriaRefs": [string],
         "seamRefs": [string],
         "mockTargets": [string],
         "sliceAnnotation": string,
         "isParameterized": boolean,
         "slowReason": string
       }
     ],
     "riskPoints": [string],
     "evidence": [string],
     "warnings": [string],
     "errors": [string],
     "nextActions": [string]
   }
   """
   )
   ```

3. **결과 검증**
   - `scenarios`가 비어 있으면 `status: "partial"`, `nextActions`에 "스펙 또는 AST 분석 결과 보완 필요" 추가.
   - `integration` 타입 시나리오에 `slowReason`이 없으면 자동으로 "통합 테스트 — 이유 미명시" 경고를 `warnings`에 추가.
   - `riskPoints`가 있으면 `warnings`에 flaky 위험 요약을 포함.

4. **결과 반환**
   - `ScenarioSet` JSON을 메인 세션으로 반환한다.

---

## 출력 (ScenarioSet)

```json
{
  "status": "ok",
  "summary": "8개 시나리오 설계 완료 (unit 5, slice 2, integration 1). 중복 2건 병합.",
  "scenarios": [
    {
      "id": "SC-001",
      "title": "재고 부족 시 주문 생성 실패",
      "type": "unit",
      "target": "com.example.order.OrderService",
      "priority": "P0",
      "given": ["재고가 0인 상품", "주문 수량 1"],
      "when": "createOrder(상품, 수량) 호출",
      "then": ["OutOfStockException 발생", "주문이 저장되지 않음"],
      "criteriaRefs": ["AC-001"],
      "seamRefs": ["OrderRepository — mock 대상"],
      "isParameterized": false,
      "slowReason": ""
    },
    {
      "id": "SC-002",
      "title": "주문 생성 API 요청/응답 검증",
      "type": "slice",
      "target": "com.example.order.OrderController",
      "priority": "P1",
      "given": ["유효한 주문 생성 요청 본문", "OrderService가 생성된 주문을 반환하도록 stub"],
      "when": "POST /api/orders 요청",
      "then": ["201 Created", "응답 JSON의 orderId가 존재"],
      "criteriaRefs": ["AC-002"],
      "seamRefs": ["OrderService — Mock(@MockBean/@MockitoBean, 프로파일)"],
      "isParameterized": false,
      "slowReason": ""
    },
    {
      "id": "SC-003",
      "title": "주문-결제 통합 흐름 검증",
      "type": "integration",
      "target": "com.example.order.OrderService",
      "priority": "P2",
      "given": ["승인된 주문", "결제 클라이언트가 성공 응답"],
      "when": "confirmAndPay(주문) 호출",
      "then": ["주문 상태가 PAID로 전이", "결제 클라이언트가 1회 호출됨"],
      "criteriaRefs": ["AC-003"],
      "seamRefs": [],
      "isParameterized": false,
      "slowReason": "실제 결제 클라이언트 연동이 필요해 단위 테스트로 커버 불가"
    }
  ],
  "riskPoints": [],
  "evidence": [],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| 선행 결과 전부 없음 | 세 입력 모두 `null` | `status: "failed"`, 선행 단계 실행 안내 |
| 일부 결과 누락 | 1~2개 입력 `null` | `status: "partial"`, 누락 항목 `warnings` 기록 후 진행 |
| `scenarios` 비어 있음 | 매핑 실패 | `status: "partial"`, 스펙/AST 보완 안내 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: read-only. spec-doc-mcp·repo-ast-mcp 접근만 허용. Write/Edit/Bash 금지.
