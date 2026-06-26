---
name: repair-tests
description: 테스트 실패 원인을 유형별로 분류하고 최소 diff 수정을 적용한 뒤 재실행 대상을 반환한다. "테스트 수정", "테스트 보정", "실패 수정", "flaky 수정"처럼 실패한 테스트의 원인 분석 및 수정이 필요한 상황에서 자동 호출된다.
---

## 목적

`run-tests`가 반환한 실패 결과를 받아 실패 유형(`TEST_COMPILE_FAILED`, `TEST_RUNTIME_FAILED`, `FLAKY_SUSPECTED`, `SPEC_MISMATCH`, `SYMBOL_UNRESOLVED`)을 분류하고 **최소 diff** 수정을 적용한다. 무작정 재생성은 금지한다. flaky 의심 시 `Thread.sleep` 대신 await/clock 주입 등 결정적 방식을 제안한다. 수정 후 `run-tests`에 재실행 대상을 전달한다. 2회 재시도 후에도 미해결이면 보고하고 중단한다. `isolation: worktree` 실행을 권장한다.

---

## 자동 호출 조건

- `run-tests`가 `failed[]` 항목을 포함한 결과를 반환할 때
- 사용자가 "테스트 수정", "테스트 보정", "실패 수정", "flaky 수정", "테스트 고쳐줘"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 7단계(조건부 — `run-tests` 실패 시에만)에서 호출될 때

## 수동 호출 예시

```
/spring-test-harness:repair-tests
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
| `failResult` | `TestRunResult` | 예 | — | `run-tests` 출력 |
| `originalTests` | `string[]` | 아니오 | `[]` | 실패한 테스트 파일 경로 |
| `relatedSources` | `string[]` | 아니오 | `[]` | 관련 프로덕션 소스 경로 |
| `retryCount` | `integer` | 아니오 | `0` | 현재 재시도 횟수 (2 이상이면 중단) |

`failResult`가 없으면 `status: "failed"`, `errors: ["failResult 없음 — run-tests 결과 필요"]` 반환.
`retryCount >= 2`이면 추가 시도 없이 `status: "failed"`, `nextActions`에 수동 검토 안내 포함.

---

## 단계별 절차

1. **입력 검증 및 재시도 한도 확인**
   - `failResult`가 없으면 즉시 `status: "failed"` 반환.
   - `retryCount >= 2`이면 추가 보정 없이 미해결 실패 보고 후 중단.

2. **실패 유형 분류**
   - `failResult.failed[].type`을 기준으로 아래 표에 따라 전략을 결정한다.

   | 유형 | 주요 원인 | 수정 전략 |
   |---|---|---|
   | `TEST_COMPILE_FAILED` | import 누락, 잘못된 시그니처 | import 보완, 시그니처 수정 |
   | `TEST_RUNTIME_FAILED` | mock 설정 오류, assertion 불일치 | mock/assertion 최소 수정 |
   | `FLAKY_SUSPECTED` | `Thread.sleep`, 타이밍 의존, 비결정적 상태 | await/clock 주입 등 결정적 방식으로 교체 |
   | `SPEC_MISMATCH` | 생성 코드가 스펙 criteria와 불일치 | spec 재참조 후 assertion 수정 |
   | `SYMBOL_UNRESOLVED` | 프로덕션 클래스 심볼 미해석 | AST 재분석 후 시그니처 정정 |

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
     "originalTests": <originalTests>,
     "relatedSources": <relatedSources>,
     "retryCount": <retryCount>
   }

   지시:
   - 실패를 유형(TEST_COMPILE_FAILED / TEST_RUNTIME_FAILED / FLAKY_SUSPECTED / SPEC_MISMATCH / SYMBOL_UNRESOLVED)으로 분류하라.
   - 무작정 전체 재생성 금지. 최소 diff 수정만 적용하라.
   - FLAKY_SUSPECTED: Thread.sleep 대신 await(AssertJ/Awaitility) 또는 clock 주입 등 결정적 방식을 제안하라. broad catch, over-mock도 제거 대상.
   - SPEC_MISMATCH: spec-doc-mcp.search_requirements로 criteria를 재확인한 후 assertion을 수정하라.
   - SYMBOL_UNRESOLVED: repo-ast-mcp.resolve_symbol로 시그니처를 재확인하라.
   - build-test-mcp.parse_junit_xml로 실패 메시지와 스택 트레이스를 정밀 파싱하라.
   - 수정 후 rerunTargets에 재실행 대상 클래스 목록을 포함하라.
   - isolation: worktree 환경에서 실행하는 것을 전제로 작업하라.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "rootCauseClass": "TEST_COMPILE_FAILED" | "TEST_RUNTIME_FAILED" | "FLAKY_SUSPECTED" | "SPEC_MISMATCH" | "SYMBOL_UNRESOLVED",
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

2회 재시도 후 미해결 예시:

```json
{
  "status": "failed",
  "summary": "2회 재시도 후에도 미해결 — 수동 검토 필요",
  "rootCauseClass": "SYMBOL_UNRESOLVED",
  "patches": [],
  "rerunTargets": [],
  "evidence": [],
  "warnings": ["retryCount=2 도달 — 자동 보정 한도 초과"],
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
| `failResult` 없음 | 입력 누락 | `status: "failed"`, 즉시 반환 |
| `retryCount >= 2` | 재시도 한도 초과 | 추가 보정 중단, 수동 검토 안내 |
| 패치 적용 실패 | Edit 도구 오류 | `errors`에 기록, 해당 파일 건너뜀 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: `isolation: worktree` 권장. broad catch/over-mock/sleep 패턴 금지. build-test-mcp + repo-ast-mcp + spec-doc-mcp 모두 접근 가능.
