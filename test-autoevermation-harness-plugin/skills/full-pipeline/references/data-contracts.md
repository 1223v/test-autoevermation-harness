# 요청·결과 데이터 계약

기존 schemaVersion:2 필드를 유지한다. 선택적 executionPolicy/executionSummary는 [공용 정책](../../../references/execution-policy.md)을 따른다.

## 입력 (HarnessRequest)

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `projectRoot` | `string` | 아니오 | `"미지정"` → 0단계 #13 질문/중단 (자동 cwd 금지) | Spring 프로젝트 루트 경로 |
| `specDocPaths` | `string[]` | 아니오 | `[]` → 무스펙 한계 기록; 요구사항 불명확 시만 질문 | 스펙 문서 경로 목록 |
| `targets` | `string[]` | 아니오 | `[]` → 요청·저장 설정·확인된 대상 사용 | 분석 대상 패키지 또는 FQCN |
| `targetModules` | `string[]` | 아니오 | `[]` → 요청·저장 설정·확인된 대상 사용 | 멀티 모듈 대상 |
| `buildTool` | `string` | 아니오 | `"미지정"` → 0단계 #5·#13 확정 | `gradle` 또는 `maven` |
| `junitPolicy` | `string` | 아니오 | `"jupiter-style"` | `jupiter-style`(BOM 위임) 또는 `strict-5x` |
| `testScope` | `string` | 아니오 | `"mixed"` | `unit` / `slice` / `integration` / `mixed` |
| `javaVersion` | `string` | 아니오 | `"미지정"` → 0단계 #13 확정 | `8`–`26` (Boot 2.x baseline 8, 3.x+ 17 — version-compatibility.md) |
| `springVersion` | `string` | 아니오 | `"미지정"` → 0단계 #4·#13 확정 | Spring Boot 버전 (예: `3.4.5`) |
| `stylePolicy` | `string` | 아니오 | `"google-java"` | 코드 스타일 정책 |
| `lspAvailable` | `boolean` | 아니오 | `true` | JDT LS 연결 여부. 공식 LSP 조회 성공을 현재 세션에서 확인한 경우에만 `true` — 미가용이면 **E-verify 게이트에서 하드 중단**(세팅은 `setup-harness` 소관) |
| `maxRepairRetries` | `integer` | 아니오 | `3` | repair-tests **진전 추적 단위**(고정 상한 아님 — #12 무진전 판정 기준 "동일 실패 3회 연속"과 정렬) |
| `domainKeywords` | `string[]` | 아니오 | `[]` | 스펙 검색 힌트 |
| `refactorAdvisory` | `object` | 아니오 | `{ "enabled": true }` | 3.5단계 제어. `enabled`·`thresholds{cyclomatic,constructorArgs}` — 정본: [refactor-advisory.md](../../../references/refactor-advisory.md) §5 |


## 출력 (PipelineResult)

```json
{
  "schemaVersion": 2,
  "status": "ok" | "partial" | "failed",
  "summary": "전체 파이프라인 결과 요약",
  "stages": {
    "ingestSpecs": { "status": "ok", "criteriaCount": 5 },
    "analyzeAst": { "status": "ok", "targetCount": 3 },
    "analyzeSource": { "status": "ok", "seamCount": 4 },
    "refactorAdvisory": { "status": "ok", "flagged": 2, "included": 1, "excluded": 1, "mode": "interactive" },
    "generateScenarios": { "status": "ok", "scenarioCount": 8 },
    "scenarioApproval": { "status": "ok", "approved": 7, "excluded": 1, "mode": "interactive" },
    "generateTests": { "status": "ok", "fileCount": 3 },
    "runTests": { "status": "ok", "passed": 8, "failed": 0 },
    "repairTests": { "status": "skipped" },
    "measureCoverage": { "status": "ok", "line": 0.97, "branch": 0.92, "method": 0.98, "class": 1.00, "gatePassed": true, "iterations": 2 },
    "verifyScenarios": { "status": "ok", "approved": 7, "satisfied": 7, "unsatisfied": 0, "missing": 0 },
    "conformanceRepair": { "status": "skipped", "rounds": 0, "fixed": 0, "regenerated": 0 }
  },
  "generatedFiles": [
    "src/test/java/com/example/order/OrderServiceTest.java",
    "src/test/java/com/example/order/OrderControllerTest.java"
  ],
  "scenarioDocs": [
    "test_docs/INDEX.md",
    "test_docs/scenarios/SC-001.md"
  ],
  "advisoryDocs": [
    "test_docs/refactoring/INDEX.md",
    "test_docs/refactoring/RA-001.md"
  ],
  "reportPaths": [
    "/example/project/build/test-results/test/TEST-com.example.order.OrderServiceTest.xml"
  ],
  "buildChanges": [],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

Markdown 보고서는 아래 구조로 출력한다.

```markdown
# Spring 테스트 하네스 실행 보고서

## 요약
- 상태: ok
- 생성된 테스트 파일: 3개
- 통과: 8 / 실패: 0

## 단계별 결과
| 단계 | 상태 | 비고 |
|---|---|---|
| ingest-specs | ok | 5개 criteria 추출 |
| analyze-ast | ok | 3개 컴포넌트 |
| analyze-source | ok | 4개 testSeam |
| 리팩토링 권고 | ok | 플래그 2 / 포함 1 / 제외 1 (대화형) → test_docs/refactoring/ 저장 |
| generate-scenarios | ok | 8개 시나리오 |
| 시나리오 승인 | ok | 승인 7 / 제외 1 (대화형) → test_docs/ 저장 |
| generate-tests | ok | 3개 파일 생성 |
| run-tests | ok | 8/8 통과 |
| repair-tests | 건너뜀 | — |
| measure-coverage | ok | 라인 0.97 / 브랜치 0.92 / 메서드 0.98 / 클래스 1.00 (2회 반복) |
| verify-scenarios | ok | 승인 7건 satisfied 7 / unsatisfied 0 / missing 0 |
| 적합성 자동 보정 | 건너뜀 | unmet 없음 (있으면: 1라운드, fixer 보정 1 / 재생성 0) |

## 시나리오 적합성 (test_docs/)
- 산출물: `test_docs/INDEX.md` (시나리오↔테스트코드↔결과 매핑)
- 승인 7건 모두 satisfied (given/when/then 충족)

## 리팩토링 권고 (test_docs/refactoring/)
- 플래그 2건 (complexity 1 / testability 1) — 포함 1 / 제외 1
- 산출물: `test_docs/refactoring/INDEX.md`, `RA-001.md`, `RA-002.md`

## 경고
없음

## 다음 조치
없음
```
