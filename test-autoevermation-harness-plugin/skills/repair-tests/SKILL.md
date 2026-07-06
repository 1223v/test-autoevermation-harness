---
name: repair-tests
description: 테스트 실패 원인을 유형별로 분류하고 최소 diff 수정을 적용한 뒤 재실행 대상을 반환한다. "테스트 수정", "테스트 보정", "실패 수정", "flaky 수정"처럼 실패한 테스트의 원인 분석 및 수정이 필요한 상황에서 자동 호출된다.
---

## 목적

`run-tests`가 반환한 실패 결과를 받아 실패 유형(`TEST_COMPILE_FAILED`, `TEST_RUNTIME_FAILED`, `FLAKY_SUSPECTED`, `SPEC_MISMATCH`, `SYMBOL_UNRESOLVED`)을 분류하고 **최소 diff** 수정을 적용한다. 추가로 **모드 B(적합성 보정)**: full-pipeline 10.5단계가 전달하는 `nonconformantItems[]`(10단계 verifier의 `unsatisfied` 시나리오 — 테스트는 통과하지만 시나리오와 불일치)를 `SCENARIO_NONCONFORMANT`로 보정한다. 무작정 재생성은 금지한다. flaky 의심 시 `Thread.sleep` 대신 await/clock 주입 등 결정적 방식을 제안한다. 수정 후 `run-tests`에 재실행 대상을 전달한다. **그린이 될 때까지 재시도**하되 — `retryCount`/`maxRepairRetries`는 진전 추적 단위일 뿐 고정 상한이 아니다(fallback-policy.md #12) — **직전과 동일한 실패 집합이 3회 연속(무진전)**이면 `status: "partial"`로 잔여 실패를 전량 보고하고 중단한다. `isolation: worktree` 실행을 권장한다.

---

## MCP 필수 (대체 금지)

이 스킬은 `build-test` + `repo-ast` + `spec-doc` MCP 도구가 **필수**다. 도구 미가용(도구 없음·호출 실패·연결 끊김)이면 Grep/Read/직접 파싱으로 **대체하지 말고** `status:"failed"` + remediation(fallback-policy #20)으로 즉시 중단한다. 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 연결이 검증되어 있어야 한다.

---

## 자동 호출 조건

- `run-tests`가 `failed[]` 항목을 포함한 결과를 반환할 때
- 사용자가 "테스트 수정", "테스트 보정", "실패 수정", "flaky 수정", "테스트 고쳐줘"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 7단계(조건부 — `run-tests` 실패 시에만)에서 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:repair-tests
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "failResult": { ... },
  "originalTests": ["src/test/java/com/example/order/OrderServiceTest.java"],
  "relatedSources": ["src/main/java/com/example/order/OrderService.java"],
  "retryCount": 0
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `failResult` | `TestRunResult` | 조건부 | — | `run-tests` 출력. `nonconformantItems`가 있으면 생략 가능(모드 B) |
| `nonconformantItems` | `object[]` | 아니오 | `[]` | (모드 B) 10단계 `ConformanceResult.unmet`의 `unsatisfied` 항목 — `{scenarioId, testClass, testMethods, verdict, nonconformanceClass, notes}` |
| `originalTests` | `object[]\|string[]` | 아니오 | `[]` | 실패한 테스트 파일 — `{path, content}` 객체 또는 경로 문자열(경로만 전달 시 test-fixer가 Read로 로드) |
| `relatedSources` | `object[]\|string[]` | 아니오 | `[]` | 관련 프로덕션 소스 — `{path, fqcn}` 객체 또는 경로 문자열(경로만 전달 시 test-fixer가 repo-ast로 FQCN 해석) |
| `springProfile` | `object\|null` | 아니오 | `null` | 0단계 확정 버전 프로파일([version-compatibility.md](../../references/version-compatibility.md)). 미전달 시 기존 테스트·대상 소스 import를 정본으로 판별 |
| `scenarioDocs` | `string[]` | 아니오 | `[]` | 실패 테스트 `scenarioRef`의 `test_docs/scenarios/<id>.md` 경로 (then 단언 근거) |
| `retryCount` | `integer` | 아니오 | `0` | 현재 재시도 횟수 (진전 추적 단위 — 고정 상한 아님, #12) |

`failResult`와 `nonconformantItems`가 모두 없으면 `status: "failed"`, `errors: ["failResult 없음 — run-tests 결과 필요"]` 반환.
직전과 **동일한 실패 집합이 3회 연속(무진전)**이면 추가 시도 없이 `status: "partial"`로 잔여 실패를 전량 보고하고 `nextActions`에 수동 검토 안내를 포함한다(#12).

---

## 단계별 절차

1. **입력 검증 및 진전 확인**
   - `failResult`와 `nonconformantItems`가 모두 없으면 즉시 `status: "failed"` 반환.
   - 직전 대비 실패가 줄어드는 한 계속 보정한다. **동일 실패 집합이 3회 연속(무진전)**이면 추가 보정 없이 `status: "partial"`로 잔여 실패를 전량 보고 후 중단(#12).

2. **실패 유형 분류**
   - `failResult.failed[].type`을 기준으로 아래 표에 따라 전략을 결정한다.

   | 유형 | 주요 원인 | 수정 전략 |
   |---|---|---|
   | `TEST_COMPILE_FAILED` | import 누락, 잘못된 시그니처 | import 보완, 시그니처 수정 |
   | `TEST_RUNTIME_FAILED` | mock 설정 오류, assertion 불일치 | mock/assertion 최소 수정 |
   | `FLAKY_SUSPECTED` | `Thread.sleep`, 타이밍 의존, 비결정적 상태 | await/clock 주입 등 결정적 방식으로 교체 |
   | `SPEC_MISMATCH` | 생성 코드가 스펙 criteria와 불일치 | spec 재참조 후 assertion 수정 |
   | `SYMBOL_UNRESOLVED` | 프로덕션 클래스 심볼 미해석 | AST 재분석 후 시그니처 정정 |
   | `SCENARIO_NONCONFORMANT` | (모드 B) 통과 테스트가 시나리오 given/when/then과 불일치 — 잘못된 target 호출·mock 어긋남·then 부족 | scenarioDocs + repo-ast `methodCalls` 대조 → `// when`을 시나리오 `target`으로 교정, given/then 최소 수정(단언 강화만 허용) |

3. **subagent 호출**

   ```
   Task(
     subagent_type="test-fixer",
     model="inherit",
     prompt="""
   다음 실패 결과를 분석하고 최소 diff로 수정하라.

   입력:
   {
     "failResult": <failResult>,
     "nonconformantItems": <nonconformantItems>,
     "originalTests": <originalTests>,
     "relatedSources": <relatedSources>,
     "springProfile": <springProfile>,
     "scenarioDocs": <scenarioDocs>,
     "retryCount": <retryCount>
   }

   지시:
   - 실패를 유형(TEST_COMPILE_FAILED / TEST_RUNTIME_FAILED / FLAKY_SUSPECTED / SPEC_MISMATCH / SYMBOL_UNRESOLVED / SCENARIO_NONCONFORMANT)으로 분류하라.
   - 무작정 전체 재생성 금지. 최소 diff 수정만 적용하라.
   - 수정 시 생성 원칙을 유지하라: BDD 3단(// given → // when → // then) 구조·BDDMockito given().willReturn() 스타일·메서드명 <scenarioRefSlug>_<행위>와 javadoc scenarioRef/criteriaRef 보존(10단계 verify-scenarios 매핑 의존)·springProfile 관용구(javax/jakarta·junit4/jupiter·@MockBean/@MockitoBean, 정본 references/version-compatibility.md). then 단언 완화·축소 금지.
   - springProfile이 null이면 기존 테스트·대상 소스의 실제 import를 정본으로 관용구를 판별하라.
   - FLAKY_SUSPECTED: Thread.sleep 대신 await(AssertJ/Awaitility) 또는 clock 주입 등 결정적 방식을 제안하라. broad catch, over-mock도 제거 대상.
   - SPEC_MISMATCH: spec-doc-mcp.search_requirements로 criteria를 재확인한 후 assertion을 수정하라.
   - SYMBOL_UNRESOLVED: repo-ast-mcp.resolve_symbol로 시그니처를 재확인하라.
   - SCENARIO_NONCONFORMANT(모드 B, nonconformantItems 존재 시): 테스트가 통과 중이어도 시나리오와 불일치하면 보정하라 — scenarioDocs와 repo-ast parse_java_file의 methodCalls를 대조해 // when 호출을 시나리오 target 메서드로 교정하고, given stub·then 단언을 시나리오에 맞게 최소 수정(단언 강화만 허용, 완화 금지). 수정 후 methodCalls로 target 호출을 재확인하라. 교정으로 green 테스트가 red가 될 수 있으며 이는 정상이다(이어지는 실패는 통상 절차로 보정).
   - build-test-mcp.parse_junit_xml로 실패 메시지와 스택 트레이스를 정밀 파싱하라.
   - 수정 후 rerunTargets에 재실행 대상 클래스 목록을 포함하라.
   - isolation: worktree 환경에서 실행하는 것을 전제로 작업하라.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "rootCauseClass": "TEST_COMPILE_FAILED" | "TEST_RUNTIME_FAILED" | "FLAKY_SUSPECTED" | "SPEC_MISMATCH" | "SYMBOL_UNRESOLVED" | "SCENARIO_NONCONFORMANT",
     "patches": [
       { "path": string, "diff": string }
     ],
     "rerunTargets": [string],
     "evidence": [string],
     "warnings": [string],
     "errors": [string],
     "nextActions": [string]
   }
   """
   )
   ```

4. **패치 적용**
   - `patches[]`의 각 diff를 해당 `path` 파일에 Edit으로 적용한다.
   - 적용 후 변경 내용을 `evidence`에 기록한다.

5. **재실행 요청**
   - `rerunTargets`를 `run-tests` 스킬에 전달해 재실행을 요청한다.
   - `retryCount`를 1 증가시켜 전달한다.

6. **결과 반환**
   - `RepairResult` JSON을 메인 세션으로 반환한다.

---

## 출력 (RepairResult)

```json
{
  "status": "ok",
  "summary": "1건 수정 완료 — TEST_RUNTIME_FAILED: mock stubbing 누락 보완",
  "rootCauseClass": "TEST_RUNTIME_FAILED",
  "patches": [
    {
      "path": "src/test/java/com/example/order/OrderServiceTest.java",
      "diff": "@@ -45,6 +45,7 @@\n+        when(orderRepository.findById(1L)).thenReturn(Optional.of(order));\n"
    }
  ],
  "rerunTargets": ["com.example.order.OrderServiceTest"],
  "evidence": ["OrderServiceTest.java 패치 적용 완료"],
  "warnings": [],
  "errors": [],
  "nextActions": ["run-tests 재실행: rerunTargets 전달"]
}
```

무진전(동일 실패 3회 연속) 예시:

```json
{
  "status": "partial",
  "summary": "동일 실패 3회 연속(무진전) — 잔여 실패 보고, 수동 검토 필요",
  "rootCauseClass": "SYMBOL_UNRESOLVED",
  "patches": [],
  "rerunTargets": [],
  "evidence": [],
  "warnings": ["동일 실패 집합 3회 연속 — 무진전 판정(#12), 자동 보정 중단"],
  "errors": ["SYMBOL_UNRESOLVED: PaymentClient 시그니처 해석 실패"],
  "nextActions": [
    "프로덕션 소스의 PaymentClient 시그니처를 수동 확인하라",
    "JDT LS 활성화 후 analyze-source 재실행을 고려하라"
  ]
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| `failResult`·`nonconformantItems` 모두 없음 | 입력 누락 | `status: "failed"`, 즉시 반환 |
| 무진전 (동일 실패 3회 연속) | 진전 없음 | `partial`로 잔여 전량 보고 후 중단, 수동 검토 안내 (#12) |
| 패치 적용 실패 | Edit 도구 오류 | `errors`에 기록, 해당 파일 건너뜀 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: `isolation: worktree` 권장. broad catch/over-mock/sleep 패턴 금지. build-test-mcp + repo-ast-mcp + spec-doc-mcp 모두 접근 가능.
