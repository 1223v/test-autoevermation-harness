---
name: edit-tests
description: 사용자가 지목한 기존 테스트 코드를 repo-ast AST 분석 근거로 직접 편집한다(테스트 메서드 이름 변경, 단언 추가·조정, 테스트 파일 정리·리팩토링). "테스트 리팩토링", "이 테스트 메서드 이름 바꿔줘", "단언 추가해줘", "이 테스트 파일 정리해줘", "테스트 코드 편집"처럼 특정 테스트의 직접 편집이 필요한 상황에서 자동 호출된다. 실패 테스트의 원인 보정은 repair-tests, 테스트 재생성·커버리지 상향은 full-pipeline이 담당한다.
---

## 목적

full-pipeline **밖에서**(또는 파이프라인 종료 후) 사용자가 **명시적으로 지목한** 기존 테스트 코드를 편집한다. `test-editor` 서브에이전트에 위임하며, 모든 편집은 `repo-ast` MCP의 AST 분석에 근거한다(추측 편집 금지). 이 스킬은 테스트를 **실행하지 않는다** — 편집 후 재실행·검증은 `/test-autoevermation-harness-plugin:run-tests`로 안내한다.

**경계(3분법)** — 이 스킬은 아래 셋 중 첫 번째만 담당한다:

| 요청 | 담당 |
|---|---|
| 지목한 테스트의 직접 편집(이름 변경·단언 추가/조정·정리) | **edit-tests** (이 스킬) |
| 실패·에러 테스트의 원인 보정 | `repair-tests` |
| 테스트 재생성·커버리지 상향·파이프라인 재개 | `full-pipeline` |

범위를 넘는 요청은 편집하지 않고 해당 스킬로 회송한다.

---

## MCP 필수 (대체 금지)

이 스킬은 `repo-ast` MCP 도구(`parse_java_file`·`resolve_symbol`·`extract_test_targets`)가 **필수**다. 미가용 시 처리(Grep/Read/직접 파싱 대체 금지 · `status:"failed"` + remediation · 즉시 중단)는 [fallback-policy.md](../../references/fallback-policy.md) #20을 그대로 따른다 — 연결은 `setup-harness`(E3b)가 세팅·검증한다.

---

## 자동 호출 조건

- 사용자가 특정 테스트 파일/클래스/메서드를 지목하고 "테스트 리팩토링", "이 테스트 메서드 이름 바꿔줘", "단언 추가해줘", "이 테스트 파일 정리해줘", "테스트 코드 편집" 등 **직접 편집**을 요청할 때
- **자동 호출되지 않아야 하는 경우**: 실패/에러 보정(→ `repair-tests`), "테스트 다시 생성 / 재실행 / 커버리지 더 올려 / 보완 / 업데이트"(→ `full-pipeline`)

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:edit-tests
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `projectRoot` | string | 예 | (현재 프로젝트 루트) | Spring 프로젝트 루트 절대 경로 |
| `targets` | object[] | 조건부 | — | 편집 대상 `{path, class?, methods?}`. 미전달 시 1단계에서 사용자 지시·Glob으로 해석 |
| `editRequest` | string | 예 | — | 사용자 편집 지시 원문 |
| `springProfile` | object\|null | 아니오 | `null` | 버전 프로파일. 미전달 시 대상 파일 import를 정본으로 판별 |

---

## 단계별 절차

### 1. 대상 해석

사용자 지시에서 편집 대상 테스트 파일·메서드를 식별한다.
- 경로가 명시되면 그대로 `targets`로 사용한다.
- 클래스/메서드 이름만 주어지면 `Glob`으로 `src/test/**/<Name>*.java`를 찾고, 필요하면 `extract_test_targets`로 테스트↔대상 매핑을 확인한다.
- **대상이 모호하면**(여러 파일 후보, 어떤 메서드인지 불명확) `AskUserQuestion`으로 확정한다. (이 스킬은 메인 세션에서 실행되므로 질문이 가능하다. 서브에이전트는 질문할 수 없으므로 위임 **전에** 대상을 확정한다.)

### 2. 범위 밖 요청 회송 판정

`editRequest`가 실패 보정성(스택트레이스·컴파일 오류·"깨졌다 고쳐줘")이면 `repair-tests`로, 재생성·커버리지·재개성이면 `full-pipeline`로 안내하고 이 스킬을 종료한다(편집하지 않음).

### 3. test-editor 위임

```
Task(
  subagent_type="test-editor",
  model="inherit",
  prompt="""
사용자가 지목한 기존 테스트를 최소 diff로 편집하라. 실행하지 말고 편집만 하라.

입력:
{
  "projectRoot": <projectRoot>,
  "targets": <targets>,
  "editRequest": <editRequest 원문>,
  "springProfile": <springProfile 또는 null>
}

지시:
- 편집 전 repo-ast parse_java_file로 대상 파일 구조(메서드·import·methodCalls)를 확인하라. 추측으로 편집하지 마라.
- 사용자가 지시한 변경만 최소 diff로 적용하라(무관한 포맷팅·리네이밍 금지). "정리" 지시가 있을 때만 정리 범위를 넓혀라.
- BDD 3단(// given → // when → // then) 구조와 메서드 javadoc의 scenarioRef/criteriaRef 태그를 보존하라(9단계 verify-scenarios 매핑 의존). 메서드명을 바꾸면 대응 시나리오 문서와의 슬러그 연관이 끊길 수 있으므로 warnings에 남겨라.
- 단언 추가·강화는 허용, then 단언의 완화·삭제는 사용자가 명시 요청한 경우에만 하고 warnings에 기록하라.
- 단언에 쓸 심볼·타입은 resolve_symbol로 시그니처를 확인하라. springProfile이 null이면 대상 파일 import를 정본으로 관용구(javax/jakarta·junit4/jupiter·@MockBean/@MockitoBean)를 판별하라.
- 편집 후 parse_java_file로 재파싱해 구문이 깨지지 않았는지 검증하라. 깨졌으면 해당 Edit를 되돌려라.
- 요청이 실패 보정이면 routedTo="repair-tests", 재생성/커버리지면 routedTo="full-pipeline"으로 편집 없이 반환하라.
- Bash가 없으므로 테스트를 실행하지 마라. nextActions에 /test-autoevermation-harness-plugin:run-tests 실행 안내를 포함하라.
- 결과를 아래 JSON 스키마에 맞게 반환하라.

출력 스키마:
{
  "status": "ok" | "partial" | "failed",
  "summary": string,
  "edits": [ { "path": string, "kind": "rename"|"assertion-add"|"assertion-adjust"|"restructure"|"cleanup", "summary": string } ],
  "routedTo": "repair-tests" | "full-pipeline" | null,
  "evidence": [string],
  "warnings": [string],
  "errors": [string],
  "nextActions": [string]
}
"""
)
```

### 4. 결과 보고

`test-editor`의 `TestEditResult`를 사용자에게 요약 보고한다. `routedTo`가 있으면 해당 스킬로 안내하고, 정상 편집이면 `edits[]`와 함께 **재실행 안내**(아래 출력)를 전달한다.

---

## 출력

`test-editor`가 반환한 `TestEditResult` JSON. 정상 편집 시 `nextActions`에는 항상 다음을 포함한다:

- `/test-autoevermation-harness-plugin:run-tests`로 편집한 테스트 클래스를 재실행해 결과를 확인할 것(이 스킬·에이전트는 실행하지 않는다).

---

## 실패 처리

| 상황 | 처리 |
|---|---|
| 대상 미확정(모호) | 1단계에서 `AskUserQuestion`으로 확정. 확정 불가 시 중단 |
| 범위 밖 요청 | 2단계에서 `repair-tests`/`full-pipeline`로 회송, 편집 없음 |
| repo-ast MCP 미가용 | `status:"failed"` + remediation (fallback-policy #20), 즉시 중단 |
| 편집 후 구문 파손 | `test-editor`가 해당 Edit 롤백 → `partial`/`failed` 보고 |

---

## 보안·성능

- 편집은 `targets`에 명시된 테스트 파일로 한정한다. `src/main` 프로덕션 코드·빌드 파일은 건드리지 않는다.
- `parse_java_file`은 대상 파일에만 호출한다(전체 트리 파싱 금지).
- 테스트를 실행하지 않으므로 이 스킬은 네트워크·빌드 부작용이 없다.

---

## 연결

- `/test-autoevermation-harness-plugin:run-tests` — 편집 후 재실행(필수 후속)
- `/test-autoevermation-harness-plugin:repair-tests` — 실패·에러 테스트 보정(회송 대상)
- `/test-autoevermation-harness-plugin:full-pipeline` — 테스트 재생성·커버리지 상향·파이프라인 재개(회송 대상)
