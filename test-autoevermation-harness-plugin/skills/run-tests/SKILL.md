---
name: run-tests
description: 빌드 도구를 감지하고 가장 좁은 범위의 테스트를 실행한 뒤 JUnit XML 리포트를 파싱해 결과를 반환한다. "테스트 실행", "테스트 돌리기", "빌드 테스트"처럼 테스트 수행이 필요한 상황에서 자동 호출된다.
---

## 목적

`build-test-mcp`를 통해 빌드 도구(Gradle/Maven)를 감지하고, 생성된 테스트 클래스에 한정된 가장 좁은 범위의 테스트 task를 실행한다. 표준 출력보다 surefire/JUnit XML 리포트를 우선 파싱하고, 결과를 구조화된 JSON으로 반환한다. 실패 시 `repair-tests` 스킬이 이어 호출된다.

---

## MCP 필수 (대체 금지)

이 스킬은 `build-test` MCP 도구가 **필수**다. 미가용 시 처리(Grep/Read/직접 파싱 대체 금지 · `status:"failed"`+remediation · 즉시 중단)는 [fallback-policy.md](../../references/fallback-policy.md) #20을 그대로 따른다 — 연결은 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 선검증된다.

---

## 자동 호출 조건

- 사용자가 "테스트 실행", "테스트 돌리기", "빌드 테스트", "테스트 결과 확인"과 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 6단계(`generate-tests` 완료 직후)에서 순차 호출될 때
- `repair-tests`가 패치를 적용한 후 재실행 요청이 있을 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:run-tests
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "buildTool": "gradle",
  "task": "test",
  "targetScope": ["com.example.order.OrderServiceTest"]
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `buildTool` | `string` | 아니오 | `"미지정"` → auto-detect | `gradle` 또는 `maven` |
| `task` | `string` | 아니오 | `"미지정"` → auto-detect | 실행할 테스트 task 이름 |
| `targetScope` | `object\|string[]` | 아니오 | `{}` → 생성된 파일 전체 | 실행 대상 — 정본 형상은 test-runner 에이전트의 `{classes[], packages[], methods[]}`. string[] 전달 시 `classes`로 매핑 |
| `projectRoot` | `string` | 아니오 | 현재 작업 디렉터리 | 프로젝트 루트 절대 경로 |
| `rerunTargets` | `string[]` | 아니오 | `[]` | repair-tests가 전달하는 재실행 대상 |

`buildTool`이 `"미지정"`이면 `build-test-mcp.detect_build_tool`로 auto-detect. 탐지 실패 시 `BUILD_TOOL_UNDETECTED` 오류로 즉시 반환.

---

## 단계별 절차

1. **빌드 도구 감지**
   - `buildTool`이 `"미지정"`이면 `build-test-mcp.detect_build_tool`을 호출한다.
   - 감지 실패 시 `status: "failed"`, `errors: ["BUILD_TOOL_UNDETECTED"]` 반환.

2. **테스트 task 탐지**
   - `task`가 `"미지정"`이면 `build-test-mcp.list_test_tasks`로 사용 가능한 task 목록을 조회한다.
   - Gradle: `test` task 기본, 통합은 `integrationTest`. Maven: `test`(Surefire) 기본, 통합은 `verify`(Failsafe). (build-test `list_test_tasks` 반환과 일치; `run_targeted_tests`는 `mvn -B test -Dtest=` 실행.)

3. **subagent 호출**

   ```
   Task(
     subagent_type="test-runner",
     model="inherit",
     prompt="""
   다음 입력으로 테스트를 실행하라.

   입력:
   {
     "buildTool": <buildTool>,
     "task": <task>,
     "targetScope": <targetScope (string[]이면 {classes: [...]}로 매핑)>,
     "projectRoot": <projectRoot>,
     "rerunTargets": <rerunTargets>
   }

   지시:
   - build-test-mcp의 `run_targeted_tests` 도구를 사용하라.
   - targetScope가 있으면 해당 클래스만 실행하라(Gradle: --tests, Maven: -Dtest=).
   - rerunTargets가 있으면 해당 클래스를 우선 실행하라.
   - 전체 test task 실행은 targetScope가 비어 있을 때만 fallback으로 허용한다.
   - 표준 출력보다 surefire XML / JUnit XML 리포트를 우선 파싱하라(build-test-mcp.parse_junit_xml 사용).
   - 실제 네트워크 호출을 금지한다. 쉘 인자를 반드시 escaping하라.
   - Write/Edit 도구를 사용하지 마라.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "passed": integer,
     "failed": [
       {
         "test": string,
         "type": "TEST_COMPILE_FAILED" | "TEST_RUNTIME_FAILED" | "FLAKY_SUSPECTED",
         "message": string,
         "stackTrace": string
       }
     ],
     "reportPaths": [string],
     "failureClasses": [string],
     "evidence": [string],
     "warnings": [string],
     "errors": [string],
     "nextActions": [string]
   }
   """
   )
   ```

4. **결과 평가**
   - `failed`가 비어 있으면 `status: "ok"`.
   - `failed`가 있으면 `status: "partial"` 또는 `"failed"` 설정 후 `nextActions`에 `repair-tests` 호출 안내 추가.
   - `FLAKY_SUSPECTED` 유형이 있으면 `warnings`에 "flaky 의심 — sleep/nondeterminism 제거 필요" 추가.

5. **결과 반환**
   - `TestRunResult` JSON을 메인 세션으로 반환한다.

---

## 출력 (TestRunResult)

```json
{
  "status": "ok",
  "summary": "5개 테스트 통과, 0개 실패",
  "passed": 5,
  "failed": [],
  "reportPaths": [
    "build/test-results/test/TEST-com.example.order.OrderServiceTest.xml"
  ],
  "failureClasses": [],
  "evidence": ["JUnit XML 파싱 완료"],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

실패 포함 예시:

```json
{
  "status": "partial",
  "summary": "4개 통과, 1개 실패",
  "passed": 4,
  "failed": [
    {
      "test": "com.example.order.OrderServiceTest#재고_부족_시_예외_발생",
      "type": "TEST_RUNTIME_FAILED",
      "message": "Expected InsufficientStockException but was NullPointerException",
      "stackTrace": "..."
    }
  ],
  "reportPaths": ["build/test-results/test/TEST-com.example.order.OrderServiceTest.xml"],
  "failureClasses": ["com.example.order.OrderServiceTest"],
  "evidence": [],
  "warnings": [],
  "errors": [],
  "nextActions": ["repair-tests 호출 권장"]
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| `BUILD_TOOL_UNDETECTED` | 빌드 도구 감지 실패 | `status: "failed"`, 즉시 반환 |
| `TEST_COMPILE_FAILED` | 컴파일 오류 | `failed[]`에 기록, `repair-tests` 안내 |
| `TEST_RUNTIME_FAILED` | 런타임 오류 | `failed[]`에 기록, `repair-tests` 안내 |
| `FLAKY_SUSPECTED` | 비결정적 실패 패턴 | `failed[]`에 기록, `warnings`에 flaky 경고 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: 쉘 인자 escaping 필수. 실제 네트워크 호출 금지. Write/Edit 권한 없음.
성능: targetScope 한정 실행 기본. 전체 task는 fallback.
