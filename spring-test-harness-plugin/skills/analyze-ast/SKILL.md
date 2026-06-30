---
name: analyze-ast
description: JavaParser 기반으로 Spring 프로젝트의 클래스/메서드/애노테이션/의존 그래프를 구조적으로 추출한다. "AST 분석", "구조 추출", "클래스 의존 그래프"처럼 코드 구조 파악이 필요한 상황에서 자동 호출된다.
---

## 목적

JavaParser 기반 `repo-ast-mcp`를 통해 대상 패키지·클래스의 public 메서드, Spring stereotype 애노테이션, 필드, 의존 그래프를 **구조만** 정밀 추출한다. 코드 본문 유출 및 심볼 추측을 금지하고, unresolved symbol은 별도 배열로 분리한다. 결과는 `analyze-source` 및 `generate-scenarios` 스킬의 입력으로 쓰인다.

---

## 자동 호출 조건

- 사용자가 "AST 분석", "구조 추출", "클래스 의존 그래프", "Spring 컴포넌트 목록"과 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 1단계에서 `ingest-specs`와 병렬로 호출될 때

## 수동 호출 예시

```
/spring-test-harness:analyze-ast
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "projectRoot": "/path/to/spring-project",
  "targets": ["com.example.order"],
  "targetModules": ["order-service"]
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `projectRoot` | `string` | 아니오 | `"미지정"` → 현재 작업 디렉터리 | 분석할 Spring 프로젝트 루트 |
| `targets` | `string[]` | 아니오 | `[]` → auto-detect | 분석 대상 패키지 또는 FQCN 목록 |
| `targetModules` | `string[]` | 아니오 | `[]` → auto-detect | 멀티 모듈 프로젝트에서 대상 모듈 이름 |

`targets`가 비어 있으면 `repo-ast-mcp.list_spring_components`로 전체 컴포넌트를 자동 탐색한다. 전체 트리 파싱은 금지하고 결과 후보를 `testTargets`로 제안한다.

---

## 단계별 절차

1. **입력 정규화**
   - `projectRoot`가 `"미지정"`이면 현재 작업 디렉터리를 사용한다.
   - `targets`가 비어 있으면 auto-detect 플래그를 설정한다.

2. **subagent 호출**

   ```
   Task(
     subagent_type="ast-structure-analyzer",
     model="inherit",
     prompt="""
   다음 입력으로 AST 구조를 추출하라.

   입력:
   {
     "projectRoot": <projectRoot>,
     "targets": <targets>,
     "targetModules": <targetModules>
   }

   지시:
   - repo-ast-mcp의 `extract_test_targets`, `list_spring_components`, `resolve_symbol` 도구를 사용하라.
   - targets가 비어 있으면 `list_spring_components`로 자동 탐색한 후 대상 후보를 testTargets에 채워라.
   - 심볼을 추론하지 마라. 확인 불가 심볼은 unresolvedSymbols 배열에 분리하라.
   - 코드 본문(메서드 바디)을 반환하지 마라. AST 노드 메타(이름, 시그니처, 애노테이션)만 반환하라.
   - vendor/, build/, generated/ 디렉터리는 read deny한다.
   - 결과 캐시 키는 파일 해시로 관리하라.
   - 결과를 아래 JSON 스키마에 맞게 반환하라.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "testTargets": [
       {
         "fqcn": string,
         "kind": "controller" | "service" | "repository" | "component" | "pojo" | "unknown",
         "publicMethods": [string]
       }
     ],
     "dependencyGraph": { "nodes": [string], "edges": [ { "from": string, "to": string, "via": string } ] },
     "unresolvedSymbols": [string],
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
   - `testTargets`가 비어 있으면 `status`를 `"partial"`로 격하하고 `nextActions`에 "대상 패키지/클래스를 명시하거나 LSP 보강을 고려하라"를 추가한다.
   - `unresolvedSymbols`가 존재하면 `warnings`에 LSP 보강 권고를 추가한다.
   - `errors`에 `SYMBOL_UNRESOLVED` 또는 `UNSUPPORTED_PROJECT_SHAPE`가 있으면 partial 반환 허용.

4. **결과 반환**
   - `AstAnalysisResult` JSON을 메인 세션으로 반환한다. 코드 본문은 포함하지 않는다.

---

## 출력 (AstAnalysisResult)

```json
{
  "status": "ok",
  "summary": "3개 컴포넌트, 12개 public 메서드 추출",
  "testTargets": [
    {
      "fqcn": "com.example.order.OrderController",
      "kind": "controller",
      "publicMethods": ["createOrder(OrderRequest)", "getOrder(Long)"]
    },
    {
      "fqcn": "com.example.order.OrderService",
      "kind": "service",
      "publicMethods": ["createOrder(OrderRequest)", "findById(Long)"]
    }
  ],
  "dependencyGraph": {
    "nodes": ["com.example.order.OrderController", "com.example.order.OrderService"],
    "edges": [{ "from": "com.example.order.OrderController", "to": "OrderService", "via": "field" }]
  },
  "unresolvedSymbols": [],
  "riskPoints": ["OrderService.createOrder: 외부 HTTP 호출 의심"],
  "evidence": ["src/main/java/com/example/order 파싱 완료"],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| `SYMBOL_UNRESOLVED` | 의존 클래스 심볼 해석 불가 | `status: "partial"`, `nextActions`에 LSP 보강 권고 |
| `UNSUPPORTED_PROJECT_SHAPE` | 멀티 모듈 구조 미지원 | `status: "partial"`, 지원 범위 내 모듈만 처리 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

성능: 대상 스코프로만 파싱. 전체 트리 파싱 금지. 결과 캐시 키는 파일 해시.
보안: read-only. vendor/build/generated 디렉터리 read deny. 코드 본문 미반환.
