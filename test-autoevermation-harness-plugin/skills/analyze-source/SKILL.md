---
name: analyze-source
description: 구조가 아닌 동작 관점에서 호출 관계, 예외 흐름, DI 패턴, 트랜잭션 경계, 외부 I/O·DB·clock·randomness 등 테스트 seam을 식별한다. "호출 분석", "의존 분석", "테스트 seam", "DI 분석"처럼 동작 파악이 필요한 상황에서 자동 호출된다.
---

## 목적

`analyze-ast` 결과로 확보된 심볼 목록을 기반으로, 각 대상의 **동작** 관점 정보를 추출한다. 구체적으로 협력 객체(collaborators), 부수 효과(sideEffects), 테스트 seam(외부 DB/HTTP/clock/randomness), 트랜잭션 경계를 식별해 `generate-scenarios`가 mock 전략을 수립할 수 있도록 한다. `repo-ast-mcp`와 JDT LS를 함께 사용한다.

---

## MCP 필수 (대체 금지)

이 스킬은 `repo-ast` MCP 도구가 **필수**다. 미가용 시 처리(Grep/Read/직접 파싱 대체 금지 · `status:"failed"`+remediation · 즉시 중단)는 [fallback-policy.md](../../references/fallback-policy.md) #20을 그대로 따른다 — 연결은 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 선검증된다. 추가로 JDT LS가 **필수**다 — `lspAvailable:false`이면 AST-only degrade로 진행하지 말고 즉시 중단한다(fallback-policy #3 개정: Phase E·E7 설치/검증 실패 시 하드 중단).

---

## 자동 호출 조건

- 사용자가 "호출 분석", "의존 분석", "테스트 seam", "DI 분석", "트랜잭션 경계"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 3단계(`analyze-ast` 완료 직후)에서 순차 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:analyze-source
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "codeRoots": ["src/main/java/com/example/order"],
  "targetSymbols": ["com.example.order.OrderService"],
  "buildMetadata": { "buildTool": "gradle", "javaVersion": "17" }
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `codeRoots` | `string[]` | 아니오 | `[]` → `analyze-ast` 결과에서 추론 | 분석할 소스 루트 경로 |
| `targetSymbols` | `string[]` | 아니오 | `[]` → `analyze-ast.testTargets[].fqcn` 사용 | 분석 대상 FQCN 목록 |
| `buildMetadata` | `object` | 아니오 | `{}` → auto-detect | 빌드 도구, Java 버전 등 메타 |
| `astResult` | `AstAnalysisResult` | 아니오 | `null` | 이전 단계 AST 결과(있으면 재파싱 생략) |
| `lspAvailable` | `boolean` | 예 (사실상) | `false` | JDT LS 연결 여부 — `false`면 진행 금지, 즉시 중단(fallback-policy #3) |

`targetSymbols`가 비어 있고 `astResult`도 없으면 `status: "partial"`을 즉시 반환하고 `analyze-ast` 선행 실행을 안내한다.

---

## 단계별 절차

1. **입력 정규화**
   - `targetSymbols`가 비어 있으면 `astResult.testTargets[].fqcn`을 사용한다.
   - `lspAvailable` 게이트: 상단 「MCP 필수」 절의 규칙(#3)을 여기서 1회만 적용한다 — `false`면 즉시 `status:"failed"` 중단. (이 게이트는 이 단계에서 단 한 번 판정하며 아래 절차·검증에서 재판정하지 않는다.)

2. **subagent 호출**

   ```
   Task(
     subagent_type="source-code-analyzer",
     model="inherit",
     prompt="""
   다음 입력으로 동작 관점 분석을 수행하라.

   입력:
   {
     "codeRoots": <codeRoots>,
     "targetSymbols": <targetSymbols>,
     "buildMetadata": <buildMetadata>,
     "lspAvailable": <lspAvailable>
   }

   지시:
   - repo-ast-mcp의 `resolve_symbol`, `parse_java_file` 도구를 사용해 각 대상의 호출 그래프를 탐색하라.
   - `lspAvailable=true` 전제(Phase E·E7이 보장, #3 — 게이트 판정은 호출자가 이미 수행)로 JDT LS 결과를 정의이동·참조탐색 보강에 활용하라.
   - 각 대상의 외부 의존(DB/HTTP/clock/random)을 식별해 testSeams에 기록하라.
   - 동작 흐름과 예외 경로(checked/unchecked exception, 롤백 조건)를 분리해 기술하라.
   - DI 패턴(@Autowired, 생성자 주입, @Value)과 트랜잭션 경계(@Transactional)를 명시하라.
   - 대상 심볼 그래프만 탐색하라. vendor/build/generated read deny.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "collaborators": [
       {
         "fqcn": string,
         "role": string,
         "injectionType": "constructor" | "field" | "setter" | "unknown",
         "mockable": boolean
       }
     ],
     "sideEffects": [string],
     "testSeams": [string],
     "transactionBoundaries": [string],
     "exceptionFlows": [
       { "exceptionType": string, "handledIn": string, "responseMapping": string }
     ],
     "externalDependencies": [
       { "kind": "db" | "http" | "clock" | "random" | "filesystem" | "messaging" | "other",
         "symbol": string, "seamSuggestion": string }
     ],
     "evidence": [string],
     "warnings": [string],
     "errors": [string],
     "nextActions": [string]
   }
   """
   )
   ```

3. **결과 검증**
   - `testSeams`가 비어 있으면 `warnings`에 "seam 미식별 — 순수 로직 또는 분석 범위 확인 필요"를 추가한다.

4. **결과 반환**
   - `SourceAnalysisResult` JSON을 메인 세션으로 반환한다. 코드 본문은 포함하지 않는다.

---

## 출력 (SourceAnalysisResult)

```json
{
  "status": "ok",
  "summary": "OrderService 분석 완료 — 2개 협력 객체, 3개 testSeam 식별",
  "collaborators": [
    { "fqcn": "com.example.order.OrderRepository", "role": "저장소", "injectionType": "constructor", "mockable": true },
    { "fqcn": "com.example.payment.PaymentClient", "role": "외부 결제 HTTP 클라이언트", "injectionType": "constructor", "mockable": true }
  ],
  "sideEffects": ["OrderRepository.save: DB 쓰기", "PaymentClient.charge: 외부 HTTP 호출"],
  "testSeams": [
    "OrderRepository — @DataJpaTest 또는 mock 대상",
    "PaymentClient — HTTP 호출, mock 필수",
    "Clock — LocalDateTime.now() 직접 호출, clock 주입 권장"
  ],
  "transactionBoundaries": [
    "createOrder — @Transactional(REQUIRED), rollbackFor=RuntimeException"
  ],
  "exceptionFlows": [
    { "exceptionType": "InsufficientStockException", "handledIn": "GlobalExceptionHandler", "responseMapping": "409 CONFLICT" }
  ],
  "externalDependencies": [
    { "kind": "http", "symbol": "com.example.payment.PaymentClient", "seamSuggestion": "mock 필수 (@MockitoBean/@MockBean 프로파일)" }
  ],
  "evidence": ["OrderService.java 분석 완료"],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| `SYMBOL_UNRESOLVED` | 대상 심볼 탐색 불가 | `status: "partial"`, LSP 보강 권고 |
| LSP 미가용 | `lspAvailable: false` | 즉시 `status:"failed"`로 중단(AST-only degrade 금지, fallback-policy #3 개정) |
| `targetSymbols` 미제공 + `astResult` 없음 | — | `status: "partial"`, `analyze-ast` 선행 실행 안내 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: read-only. 대상 심볼 그래프만 탐색. vendor/build/generated read deny.
성능: `astResult` 재사용으로 이중 파싱 방지. JDT LS와 AST 역할 분리로 중복 비용 방지.
