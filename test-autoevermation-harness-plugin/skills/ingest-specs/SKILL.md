---
name: ingest-specs
description: 스펙 문서를 인덱싱하고 acceptance criteria를 정규화한다. "스펙 문서 리뷰", "요구사항 분석", "스펙 인제스트"처럼 문서 처리가 필요한 상황에서 자동 호출된다.
---

## 목적

스펙 문서(요구사항서, API 설계서, 도메인 규격 등)를 받아 누락 없이 요약하고, 테스트 가능한 acceptance criteria / 비즈니스 규칙 / edge case / 금지사항을 Given/When/Then 형태로 정규화한다. 결과는 `generate-scenarios` 스킬의 입력으로 쓰인다.

---

## MCP 필수 (대체 금지)

이 스킬은 `spec-doc` MCP 도구가 **필수**다. 도구 미가용(도구 없음·호출 실패·연결 끊김)이면 Grep/Read/직접 파싱으로 **대체하지 말고** `status:"failed"` + remediation(fallback-policy #20)으로 즉시 중단한다. 파이프라인 시작 전 Phase E·E3b(`health` 3종 호출)에서 연결이 검증되어 있어야 한다.

---

## 자동 호출 조건

- 사용자가 "스펙 문서 리뷰", "요구사항 분석", "스펙 인제스트", "인수 조건 추출"과 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 1단계에서 AST 분석과 병렬로 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:ingest-specs
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "specDocPaths": ["docs/api-spec.md", "docs/domain-rules.yaml"],
  "priority": ["docs/api-spec.md"],
  "domainKeywords": ["주문", "결제", "재고"]
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `specDocPaths` | `string[]` | 아니오 | `[]`(없으면 미지정으로 처리) | 인덱싱할 문서 경로(allowlist 내) |
| `priority` | `string[]` | 아니오 | `[]` | 우선 처리할 문서 경로 |
| `domainKeywords` | `string[]` | 아니오 | `[]` | 검색 힌트로 쓸 도메인 키워드 |

`specDocPaths`가 비어 있으면 `SPEC_DOC_UNREADABLE(partial)` 결과로 즉시 반환하고 `nextActions`에 경로 지정 안내를 포함한다.

---

## 단계별 절차

1. **입력 검증**
   - `specDocPaths` 목록이 비어 있으면 `status: "partial"`, `errors: ["SPEC_DOC_UNREADABLE: 스펙 경로 미지정"]`을 반환한다.
   - 각 경로가 프로젝트 allowlist(프로젝트 루트 내부) 안에 있는지 확인한다. 벗어난 경로는 건너뛰고 `warnings`에 기록한다.

2. **subagent 호출**
   - 아래 형식으로 `spec-reviewer` subagent를 호출한다.

   ```
   Task(
     subagent_type="spec-reviewer",
     model="inherit",
     prompt="""
   다음 스펙 문서를 처리하라.

   입력:
   {
     "specDocPaths": <specDocPaths>,
     "priority": <priority>,
     "domainKeywords": <domainKeywords>
   }

   지시:
   - spec-doc-mcp의 `index_docs`, `search_requirements`, `extract_acceptance_criteria` 도구를 순서대로 사용하라.
   - 문서를 청크로 인덱싱하고, 테스트 가능한 acceptance criteria를 Given/When/Then으로 정규화하라.
   - 읽을 수 없는 문서는 SPEC_DOC_UNREADABLE로 보고하라.
   - 민감정보(토큰, 이메일, 접속문자열)는 redact 처리하라.
   - 긴 문서는 청크별로 분리해 처리하고, 코드 본문을 메인 컨텍스트에 노출하지 마라.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "requirements": [{ "id": string, "text": string, "section": string }],
     "acceptanceCriteria": [
       { "id": string, "given": string, "when": string, "then": string,
         "priority": "P0" | "P1" | "P2", "tags": [string], "sourceDoc": string }
     ],
     "prohibitions": [string],
     "glossary": { "<term>": "<definition>" },
     "evidence": [string],
     "warnings": [string],
     "errors": [string],
     "nextActions": [string]
   }
   """
   )
   ```

3. **결과 수집 및 검증**
   - subagent 결과에서 `acceptanceCriteria` 배열이 비어 있으면 `status`를 `"partial"`로 격하하고 `nextActions`에 "스펙 보완 또는 수동 criteria 작성 필요"를 추가한다.
   - `errors` 항목에 `SPEC_DOC_UNREADABLE`이 포함된 경우 해당 항목을 상위 레벨 `warnings`에도 기록한다.

4. **결과 반환**
   - `SpecReviewResult` JSON을 메인 세션으로 반환한다. 코드 전문은 포함하지 않는다.

---

## 출력 (SpecReviewResult)

```json
{
  "status": "ok" | "partial" | "failed",
  "summary": "처리된 문서 수, 추출된 criteria 수 요약",
  "requirements": [
    { "id": "REQ-001", "text": "주문 생성 시 재고를 확인해야 한다", "section": "3.2 주문 생성" }
  ],
  "acceptanceCriteria": [
    {
      "id": "AC-001",
      "given": "재고가 0인 상품",
      "when": "주문 생성 요청",
      "then": "400 오류와 재고 부족 메시지를 반환한다",
      "priority": "P0",
      "tags": ["order", "stock"],
      "sourceDoc": "docs/api-spec.md"
    }
  ],
  "prohibitions": ["재고 마이너스 허용 불가"],
  "glossary": { "주문": "고객이 상품을 구매하는 행위" },
  "evidence": ["docs/api-spec.md 섹션 3.2 파싱 완료"],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| `SPEC_DOC_UNREADABLE` | 문서 경로 미지정 또는 읽기 불가 | `status: "partial"`, `nextActions`에 경로 지정 안내 |
| `ALLOWLIST_VIOLATION` | 경로가 프로젝트 루트 밖 | 해당 경로 건너뜀 + `warnings` 기록 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록, 수동 처리 안내 |

2회 재시도 후에도 `failed`이면 파이프라인을 중단하고 원인을 보고한다.
