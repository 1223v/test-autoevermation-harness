---
name: refactor-advisory
description: 시나리오 생성 전에 테스트 대상 코드가 너무 복잡하거나(순환복잡도), 비효율적이거나(N+1·루프 비용), 테스트 저해 설계(강결합·정적/숨은 의존·미주입 clock/random)인지 공식문서 근거로 판정한다. "리팩토링 권고", "복잡도 검사", "테스트 적합성 판정", "N+1 검사"처럼 테스트 전 코드 품질 판정이 필요한 상황에서 자동 호출된다.
---

## 목적

`analyze-ast`(2단계)·`analyze-source`(3단계) 결과를 기반으로, 각 테스트 대상이 "지금 테스트를 붙이기에
적절한가"를 3범주(`complexity` / `testability` / `efficiency`) 기준으로 판정해 `RefactorAdvisoryResult`를
반환한다. 탐지 기준·임계값·근거 출처의 정본: [refactor-advisory.md](../../references/refactor-advisory.md) §2.

이 스킬은 **read-only 분석**까지만 수행한다. 권고 `.md`(`test_docs/refactoring/RA-*.md`) 저장·
`AskUserQuestion` 결정 게이트(포함/제외)·4단계 입력 필터링은 **다운스트림(`full-pipeline` 3.5단계)**이
수행한다(fallback-policy.md #19). 단독 호출 시에는 판정 결과만 보고한다.

---

## MCP 필수 (대체 금지)

이 스킬은 `repo-ast` MCP 도구가 **필수**다. 도구 미가용(도구 없음·호출 실패·연결 끊김)이면 Grep/Read/직접 파싱으로 **대체하지 말고** `status:"failed"` + remediation(fallback-policy #20)으로 즉시 중단한다. 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 연결이 검증되어 있어야 한다. 추가로 JDT LS가 **필수**다 — `lspAvailable:false`이면 진행을 금지하고 즉시 중단한다(fallback-policy #3 개정). 단, 이 MCP 가용성 요구는 **판정 자체의 실패(허위 양성 억제, 근거 부족 시 미플래그 등)가 non-blocking(#19)인 것과는 별개**다 — MCP 미가용은 하드 중단, 판정 보수성은 기존 정책대로 유지한다.

---

## 자동 호출 조건

- 사용자가 "리팩토링 권고", "복잡도 검사", "테스트 적합성", "N+1 검사", "테스트 저해"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 3.5단계(`analyze-source` 완료 직후)에서 순차 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:refactor-advisory
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "targetSymbols": ["com.example.order.OrderService"],
  "projectRoot": "/absolute/path/to/project",
  "thresholds": { "cyclomatic": 10 }
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `astResult` | `AstAnalysisResult` | 아니오 | `null` | 2단계 산출(있으면 재파싱 생략) |
| `sourceResult` | `SourceAnalysisResult` | 아니오 | `null` | 3단계 산출. `testSeams`·`collaborators` 신호 재사용 |
| `targetSymbols` | `string[]` | 아니오 | `[]` → `astResult.testTargets[].fqcn` 사용 | 판정 대상 FQCN 목록 |
| `projectRoot` | `string` | 아니오 | cwd | 소스 탐색 루트(allowlist 경계) |
| `lspAvailable` | `boolean` | 예 (사실상) | `false` | JDT LS 연결 여부 — `false`면 진행 금지, 즉시 중단(fallback-policy #3) |
| `thresholds` | `object` | 아니오 | refactor-advisory.md §2 기본값 | `HarnessConfig.refactorAdvisory.thresholds` 오버라이드 |

`targetSymbols`가 비어 있고 `astResult`도 없으면 `status: "partial"`을 즉시 반환하고 `analyze-ast` 선행 실행을 안내한다.

---

## 단계별 절차

1. **입력 정규화**
   - `targetSymbols`가 비어 있으면 `astResult.testTargets[].fqcn`을 사용한다.
   - `thresholds` 미지정 시 [refactor-advisory.md](../../references/refactor-advisory.md) §2 기본값
     (`cyclomatic: 10`, `constructorArgs: 7`)을 쓴다.

2. **subagent 호출**

   ```
   Task(
     subagent_type="refactor-advisor",
     model="inherit",
     prompt="""
   다음 입력으로 리팩토링 권고 판정을 수행하라.

   입력:
   {
     "astResult": <astResult>,
     "sourceResult": <sourceResult>,
     "targetSymbols": <targetSymbols>,
     "projectRoot": <projectRoot>,
     "lspAvailable": <lspAvailable>,
     "thresholds": <thresholds>
   }

   지시:
   - references/refactor-advisory.md §2의 3범주 기준·임계값·근거 출처로만 판정하라(임의 수치 금지).
   - 대상 심볼과 직접 협력 객체(1홉)의 소스만 Read/Grep하라. repo-ast는 메타 확인용(메서드 바디 미반환 — 설계 불변).
   - sourceResult.testSeams·collaborators.injectionType을 재사용해 이중 파싱을 피하라.
   - 임계 미달·근거 부족 발견은 플래그하지 마라(허위 양성 억제). 테스트/generated 코드, 순수 함수 static 유틸 제외.
   - 각 advisory에 rationaleRefs(출처 키)와 실행 가능한 recommendation을 기록하라. severity는 §2.4 규칙.
   - 재실행 시 test_docs/refactoring/의 동일 target advisory id를 재사용하라.
   - 소스 원문을 결과 JSON에 넣지 마라(경로·라인·지표만). vendor/build/generated read deny.
   - RefactorAdvisoryResult JSON으로 반환하라.
   """
   )
   ```

3. **결과 검증**
   - `advisories`가 빈 배열이면 "플래그 0건 — 전 대상 생성 적합"을 요약에 명시한다(다운스트림 게이트 생략 신호).
   - LSP 미가용이면 즉시 `status:"failed"`로 중단한다(degrade 금지, #3 개정).
   - `advisories[].signals[].evidence`가 파일:라인 형식인지, 소스 원문이 섞이지 않았는지 확인한다.

4. **결과 반환**
   - `RefactorAdvisoryResult` JSON을 메인 세션으로 반환한다. 코드 본문은 포함하지 않는다.
   - full-pipeline 3.5단계 호출이면 오케스트레이터가 이어서 권고 `.md` 저장·게이트를 수행한다
     ([refactor-advisory.md](../../references/refactor-advisory.md) §4).

---

## 출력 (RefactorAdvisoryResult)

```json
{
  "status": "ok",
  "summary": "3개 대상 중 2개 플래그 — complexity 1 / testability 2 / efficiency 1 (중복 범주 포함)",
  "advisories": [
    {
      "advisoryId": "RA-001",
      "target": "com.example.order.OrderService#createOrder",
      "categories": ["complexity", "testability"],
      "severity": "high",
      "signals": [
        { "kind": "cyclomatic", "value": 14, "threshold": 10, "evidence": "OrderService.java:42-118" },
        { "kind": "unmockable-seam", "value": "LocalDateTime.now()", "evidence": "OrderService.java:57" }
      ],
      "rationaleRefs": ["nist-500-235", "mockito-39-48", "spring-ctor-di"],
      "recommendation": [
        "검증/할인/저장 단계를 메서드 추출로 분리해 각 CC ≤ 10",
        "java.time.Clock 생성자 주입으로 now() seam화"
      ]
    }
  ],
  "cleanTargets": ["com.example.order.OrderController"],
  "evidence": ["OrderService.java CC 계산: 42-118 분기 13개"],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

전체 스키마 정본: [agents/refactor-advisor.md](../../agents/refactor-advisor.md) 「JSON 출력 스키마」.

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| LSP 미가용 | `lspAvailable: false` | 즉시 `status:"failed"`로 중단(AST+Read-only degrade 금지, #3 개정) |
| 바디 Read 불가 | 파일 접근 불가·비Java | 해당 대상 `warnings` + 시그니처 기반 부분 판정, 나머지 계속 |
| `targetSymbols` 미제공 + `astResult` 없음 | — | `status: "partial"`, `analyze-ast` 선행 실행 안내 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: read-only. 대상 심볼 그래프(1홉)만 탐색. vendor/build/generated read deny. 보안 취약점 탐지는 미포함(향후 확장).
성능: `astResult`/`sourceResult` 재사용으로 이중 파싱 방지. 다수 대상 병렬 판정.
