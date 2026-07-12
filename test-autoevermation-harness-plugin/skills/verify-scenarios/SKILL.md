---
name: verify-scenarios
description: 모든 단계(생성·실행·커버리지·뮤테이션)가 끝난 뒤, 승인된 각 BDD 시나리오가 실제로 충족되었는지(테스트가 given/when/then을 만족하는지) 검증하고, 시나리오↔테스트코드↔결과를 대상 프로젝트의 test_docs/에 정리한다. "시나리오 검증", "시나리오 만족 확인", "적합성 검증", "test_docs 정리"처럼 시나리오 충족 확인이 필요할 때 자동 호출된다.
---

## 목적

생성·통과한 테스트가 **승인된 시나리오의 BDD given/when/then을 실제로 만족하는지** 검증한다(단순 통과 여부가 아님).
검증 결과로 대상 프로젝트의 `test_docs/`(living documentation)를 **시나리오 ↔ 테스트코드 ↔ 결과**로 갱신한다.
정본: [references/scenario-docs.md](../../references/scenario-docs.md) §4.

---

## MCP 필수 (대체 금지)

이 스킬은 `repo-ast` + `build-test` MCP 도구가 **필수**다. 미가용 시 처리(Grep/Read/직접 파싱 대체 금지 · `status:"failed"`+remediation · 즉시 중단)는 [fallback-policy.md](../../references/fallback-policy.md) #20을 그대로 따른다 — 연결은 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 선검증된다.

---

## 자동 호출 조건

- 사용자가 "시나리오 검증", "시나리오 만족 확인", "적합성 검증", "test_docs 정리"와 같은 키워드를 사용할 때
- `full-pipeline` 10단계(run-tests·measure-coverage·mutation-test 완료 후)에서 순차 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:verify-scenarios
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `approvedScenarios` | object[] | 예 | — | 4.5단계에서 승인된 시나리오(`approval=approved`)만 |
| `generatedFiles` | string[] | 예 | — | 생성된 테스트 파일 경로 |
| `runResult` | object | 예 | — | 최종 실행 결과(TestRunResult). **주의: run-tests는 집계 `passed`(정수) + `failed[]`(실패 목록)만 반환하며 메서드 단위 통과 목록은 없다** — 메서드 단위 합격은 "매핑된 테스트 메서드가 `failed[]`에 없고 해당 클래스가 실행 스코프에 포함"으로 추론하고, 확증이 필요하면 `parse_junit_xml`(XML 리포트)로 보강한다 |
| `coverageResult` | object | 아니오 | `null` | 커버리지 결과(보조) |
| `projectRoot` | string | 아니오 | cwd | `test_docs/`를 만들 위치 |
| `testDocsDir` | string | 아니오 | `test_docs` | 산출물 디렉터리 |

입력(승인 시나리오/생성 파일/실행 결과) 중 하나라도 비면 `status: "failed"`를 반환하고 선행 단계를 안내한다.

---

## 단계별 절차

1. **입력 검증** — 승인 시나리오·생성 파일·실행 결과가 모두 있는지 확인. 없으면 `failed`.

2. **subagent 호출**

   ```
   Task(
     subagent_type="scenario-conformance-verifier",
     model="inherit",
     prompt="""
   승인된 각 BDD 시나리오가 실제로 충족되었는지 검증하고 test_docs/를 갱신하라.

   입력:
   {
     "approvedScenarios": <approvedScenarios>,
     "generatedFiles": <generatedFiles>,
     "runResult": <runResult>,
     "coverageResult": <coverageResult>,
     "projectRoot": <projectRoot>,
     "testDocsDir": "test_docs"
   }

   지시:
   - 시나리오 → 테스트 메서드 매핑은 scenarioRef(메서드명 sc001_… + javadoc scenarioRef/criteriaRef)로 한다.
   - target 호출 기계 대조: parse_java_file의 methodCalls로, unit/직접호출 시나리오는 시나리오 target(FQCN#method)의
     메서드 단순명이 매핑 테스트 메서드의 호출 목록에 있는지 기계 판정하라(없으면 결정적 unsatisfied +
     nonconformanceClass: WRONG_TARGET_CALL). slice는 when의 HTTP verb/경로 ↔ perform(...) 및 given stub 메서드명을 대조하라.
   - 각 시나리오를 satisfied/unsatisfied/missing으로 판정한다:
     · satisfied = 매핑된 메서드가 통과 + target 호출 일치 + // then 단언이 시나리오 then을 빠짐없이 반영.
     · unsatisfied = 매핑되나 실패·target 불일치·then 단언 부족(사유 + nonconformanceClass 기록:
       WRONG_TARGET_CALL / THEN_GAP / GIVEN_MISMATCH).
     · missing = 매핑되는 테스트 메서드 없음(nonconformanceClass: MAPPING_MISSING).
   - then 단언이 시나리오 then을 충족하는지 테스트 본문과 시나리오를 대조해 판정한다(thenCovered 충족/전체).
   - test_docs/scenarios/<id>.md의 "테스트 코드 매핑"·"검증 결과" 섹션과 INDEX.md를 references/scenario-docs.md §2 템플릿으로 갱신한다.
   - 테스트 코드를 새로 생성/수정하지 마라(검증·문서화 전용). 소스 원문·민감정보를 문서에 쓰지 마라.
   - ConformanceResult JSON으로 반환하라.
   """
   )
   ```

3. **결과 검증·게이트** — `unmet`(unsatisfied/missing)이 있으면 `status: "partial"`로 잔여를 전량 보고한다.
   전부 satisfied면 `ok`. (fallback-policy.md #16)
   - **full-pipeline에서 호출된 경우**: `unmet`과 `scenarioResults[].nonconformanceClass`를 그대로 호출자에 반환한다 —
     호출자의 **10.5단계 적합성 자동 보정 루프**(unsatisfied→test-fixer 모드 B / missing→test-code-generator 부분 재생성,
     최대 3라운드)가 자동으로 처리한다. 여기서 사용자에게 묻지 않는다.
   - **단독 호출(standalone)인 경우**: 잔여가 있으면 `AskUserQuestion`("추가 보정 시도 / partial로 종료").
     보정 선택 시 full-pipeline의 10.5단계 부분 실행을 안내한다. CI 단독 호출: `partial`로 종료.

4. **결과 반환** — `ConformanceResult` JSON과 갱신된 `docPaths`를 반환한다.

---

## 출력 (ConformanceResult)

[references/scenario-docs.md](../../references/scenario-docs.md) §4.2 스키마를 따른다.

```json
{
  "status": "partial",
  "summary": "승인 7건 중 satisfied 6 / unsatisfied 1 / missing 0",
  "totals": { "approved": 7, "satisfied": 6, "unsatisfied": 1, "missing": 0 },
  "scenarioResults": [
    { "scenarioId": "SC-001", "testClass": "com.example.order.OrderServiceTest",
      "testMethods": ["sc001_재고부족시_주문생성_실패"], "mapped": true,
      "executed": "passed", "thenCovered": "2/2", "verdict": "satisfied",
      "nonconformanceClass": null, "notes": "" }
  ],
  "unmet": ["SC-002"],
  "docPaths": ["test_docs/INDEX.md", "test_docs/scenarios/SC-001.md"],
  "warnings": [],
  "errors": [],
  "nextActions": ["SC-002: then 단언(상태 전이 검증) 보강 후 재검증"]
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| 입력 누락 | 승인 시나리오/생성 파일/실행 결과 중 누락 | `status: "failed"`, 선행 단계 실행 안내 |
| unmet 존재 | unsatisfied/missing 시나리오 존재 | `status: "partial"`, `unmet[]` 전량 보고(임의 제외 금지). 파이프라인 호출 시 10.5단계 자동 보정 루프 입력 |
| 문서 쓰기 실패 | `test_docs/` 권한/경로 문제 | `warnings` 기록 후 판정 결과는 반환 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: 검증·문서화 전용. 테스트 코드 생성/수정·Bash 금지. `projectRoot` 밖 쓰기 금지. 민감정보 기록 금지.
