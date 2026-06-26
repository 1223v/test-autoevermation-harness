---
name: full-pipeline
description: Spring 프로젝트에 대해 인터랙티브 설정·스펙 인제스트·AST 분석·소스 분석·시나리오 설계·테스트 생성·실행·보정·커버리지 게이트(near-100%)·뮤테이션 강화까지 end-to-end 파이프라인을 오케스트레이션한다. "스프링 테스트 생성", "하네스 실행", "테스트 파이프라인", "전체 테스트 자동화", "커버리지 100%"처럼 테스트 생성이 필요할 때, 그리고 후속 작업 — "테스트 다시 생성", "재실행", "커버리지 더 올려", "이 패키지만 다시", "결과 개선", "보완", "업데이트", "뮤테이션만 다시" — 처럼 이전 실행을 이어가거나 부분 재실행하는 요청에도 반드시 이 스킬을 사용한다.
---

## 목적

`HarnessRequest` JSON을 입력받아, 먼저 `configure-harness`로 인터랙티브 설정(`HarnessConfig`)을 받은 뒤, 9개 스킬(configure-harness, ingest-specs, analyze-ast, analyze-source, generate-scenarios, generate-tests, run-tests, repair-tests, measure-coverage, mutation-test)을 정해진 순서와 병렬 전략에 따라 오케스트레이션한다. 각 단계의 결과를 수렴해 다음 단계로 전달하고, **near-100% 커버리지 게이트와 뮤테이션 강화 루프**까지 수렴시킨 후 최종 Markdown 보고서와 상태 JSON을 반환한다. 미지정 필드는 `"미지정"` 또는 auto-detect로 처리하며, 비대화형(`claude -p`/CI)에서는 인터뷰를 건너뛰고 기본값을 사용한다.

---

## 실행 모드 · `_workspace/` · 부분 재실행 (성능)

**실행 모드: 서브에이전트 팬아웃/파이프라인.** 1·2단계는 상호 통신이 불필요한 독립 작업이므로 `Task(subagent_type=...)` 병렬 호출을 쓴다(에이전트 팀의 `TeamCreate`/`SendMessage` 조율 비용·지연을 피함). 이후는 순차 의존이라 파이프라인으로 잇는다.

**`_workspace/` 파일 기반 전달.** 각 단계 산출물(JSON)을 메인 컨텍스트로 통째로 옮기지 말고 `_workspace/{단계}_{에이전트}_{산출물}.json`에 저장하고, 다음 단계에는 **경로만** 전달한다. 메인 컨텍스트에는 `{status, 핵심수치, 경로}` 요약만 환원한다 → 컨텍스트 토큰 절감.

**Phase 0 컨텍스트 확인(부분 재실행).** 시작 시 `_workspace/` 존재와 요청 유형으로 실행 범위를 정한다:
- `_workspace/` 없음 → **초기 실행**(0단계부터 전체).
- 있음 + 부분 요청(예: "이 패키지만", "커버리지만 다시", "뮤테이션만") → **부분 재실행**: 영향 단계만 재호출하고 나머지는 `_workspace/`의 기존 산출물을 Read로 재사용 → 전체 재실행 회피.
- 있음 + 새 입력 → **새 실행**: 기존 `_workspace/`를 `_workspace_{YYYYMMDD_HHMMSS}/`로 이동 후 초기 실행.

**단계별 계측(timing.json).** 각 서브에이전트 완료 알림의 `total_tokens`/`duration_ms`는 **그 시점에만** 접근 가능하므로 즉시 `_workspace/timing.json`에 누적 저장한다(느린·비싼 단계 식별용). 헬퍼: `scripts/record-timing.py`.

> 전체 규약(부분 재실행 매트릭스·데이터 전달 표·에러 핸들링·timing 스키마)은 필요할 때만 로드: [references/orchestration-detail.md](references/orchestration-detail.md).

---

## 자동 호출 조건

- 사용자가 "스프링 테스트 생성", "하네스 실행", "테스트 파이프라인", "전체 테스트 자동화", "테스트 하네스 돌려줘"와 같은 키워드를 사용할 때
- CI에서 `claude -p --output-format json`으로 직접 호출될 때

## 수동 호출 예시

```
/spring-test-harness:full-pipeline
```

또는 HarnessRequest JSON과 함께:

```json
{
  "projectRoot": "/path/to/spring-project",
  "specDocPaths": ["docs/api-spec.md"],
  "targets": ["com.example.order"],
  "targetModules": [],
  "buildTool": "gradle",
  "junitPolicy": "jupiter-style",
  "testScope": "mixed",
  "javaVersion": "17",
  "springVersion": "미지정",
  "stylePolicy": "google-java",
  "lspAvailable": false,
  "maxRepairRetries": 2
}
```

---

## 입력 (HarnessRequest)

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `projectRoot` | `string` | 아니오 | `"미지정"` → 현재 작업 디렉터리 | Spring 프로젝트 루트 경로 |
| `specDocPaths` | `string[]` | 아니오 | `[]` → `"미지정"` | 스펙 문서 경로 목록 |
| `targets` | `string[]` | 아니오 | `[]` → auto-detect | 분석 대상 패키지 또는 FQCN |
| `targetModules` | `string[]` | 아니오 | `[]` → auto-detect | 멀티 모듈 대상 |
| `buildTool` | `string` | 아니오 | `"미지정"` → auto-detect | `gradle` 또는 `maven` |
| `junitPolicy` | `string` | 아니오 | `"jupiter-style"` | `jupiter-style`(BOM 위임) 또는 `strict-5x` |
| `testScope` | `string` | 아니오 | `"mixed"` | `unit` / `slice` / `integration` / `mixed` |
| `javaVersion` | `string` | 아니오 | `"미지정"` → auto-detect | `17`–`26` |
| `springVersion` | `string` | 아니오 | `"미지정"` → auto-detect | Spring Boot 버전 (예: `4.1.0`) |
| `stylePolicy` | `string` | 아니오 | `"google-java"` | 코드 스타일 정책 |
| `lspAvailable` | `boolean` | 아니오 | `false` | JDT LS 연결 여부 |
| `maxRepairRetries` | `integer` | 아니오 | `2` | repair-tests 최대 재시도 횟수 |
| `domainKeywords` | `string[]` | 아니오 | `[]` | 스펙 검색 힌트 |

### 미지정 필드 처리 원칙

- `projectRoot: "미지정"` → 현재 작업 디렉터리 사용
- `specDocPaths: []` → ingest-specs를 `status: "partial"`로 실행, 이후 단계는 스펙 없이 진행
- `targets: []` → analyze-ast가 `list_spring_components`로 auto-detect
- `buildTool: "미지정"` → `build-test-mcp.detect_build_tool`로 auto-detect
- `javaVersion: "미지정"` → `springProfile.javaBaseline`(Boot 2.x=8, 3.x+=17) 또는 빌드 파일에서 auto-detect
- `springVersion: "미지정"` → `build-test-mcp.detect_spring_profile`로 `springProfile`(Boot 2.0–4.x) 감지. 감지 실패 시 대화형=인터뷰 / CI=latest(4.x) 가정+경고. 이 프로파일이 모든 테스트 생성 관용구(javax/jakarta, junit4/jupiter, @MockBean/@MockitoBean)를 결정한다(RESEARCH_NOTES §8)
- `junitPolicy: "strict-5x"` → 빌드 파일에 version pin + CHANGELOG 경고 추가

---

## 단계별 절차

### 전처리: 입력 정규화

미지정 필드를 아래 기본값으로 채운다.

```
projectRoot       = 입력값 또는 현재 작업 디렉터리
specDocPaths      = 입력값 또는 []
targets           = 입력값 또는 []
targetModules     = 입력값 또는 []
buildTool         = 입력값 또는 "미지정"
junitPolicy       = 입력값 또는 "jupiter-style"
testScope         = 입력값 또는 "mixed"
javaVersion       = 입력값 또는 "미지정"
springVersion     = 입력값 또는 "미지정"
stylePolicy       = 입력값 또는 "google-java"
lspAvailable      = 입력값 또는 false
maxRepairRetries  = 입력값 또는 2
domainKeywords    = 입력값 또는 []
```

`junitPolicy: "strict-5x"` 감지 시 `warnings`에 "BOM 기본값(Jupiter 6.0.x)과의 버전 충돌 주의 — 명시적 version pin 필요" 추가.

---

### 0단계: configure-harness (인터랙티브 설정)

대화형 CLI에서는 `configure-harness` 스킬로 사용자에게 4항목(스펙 경로 추가 / 대상 폴더·패키지 선별 / 뮤테이션 깊이·대상 / 커버리지 임계값·제외)을 AskUserQuestion으로 질문하고 `HarnessConfig`를 만든다. 비대화형(`claude -p`/CI)에서는 인터뷰를 건너뛰고 `HarnessRequest` + RESEARCH_NOTES §6 기본값으로 `HarnessConfig`를 구성한다.

```
/spring-test-harness:configure-harness
```

산출 `HarnessConfig`는 `specDocPaths`(추가 병합), `targetScope`, `coverage{line,branch,method,class,excludes}`, `mutation{targetClasses,targetTests,mutators,mutationThreshold}`를 포함하며, 이후 모든 단계의 입력에 병합된다. 사용자가 재사용 가능한 도메인 특화 단계를 원하면 configure-harness가 `skills/<custom>/SKILL.md`를 그 자리에서 스캐폴드하고 `/spring-test-harness:<custom>`로 호출 가능하게 한다.

---

### 1단계 & 2단계: 병렬 실행 (ingest-specs + analyze-ast)

두 스킬을 동시에 호출한다. 두 결과가 모두 도착할 때까지 대기한 후 3단계로 진행한다.

**1a. ingest-specs 호출**

```
Task(
  subagent_type="spec-reviewer",
  model="inherit",
  prompt="""
입력:
{
  "specDocPaths": <specDocPaths>,
  "priority": [],
  "domainKeywords": <domainKeywords>
}

지시:
- spec-doc-mcp의 index_docs, search_requirements, extract_acceptance_criteria를 사용하라.
- 문서를 청크로 인덱싱하고 acceptance criteria를 Given/When/Then으로 정규화하라.
- 읽을 수 없는 문서는 SPEC_DOC_UNREADABLE로 보고하라.
- 민감정보(토큰/이메일/접속문자열)를 redact하라.
- SpecReviewResult JSON으로 반환하라.
"""
)
```

**1b. analyze-ast 호출 (1a와 동시)**

```
Task(
  subagent_type="ast-structure-analyzer",
  model="inherit",
  prompt="""
입력:
{
  "projectRoot": <projectRoot>,
  "targets": <targets>,
  "targetModules": <targetModules>
}

지시:
- repo-ast-mcp의 extract_test_targets, list_spring_components, resolve_symbol을 사용하라.
- targets가 비어 있으면 list_spring_components로 자동 탐색하라.
- 심볼을 추론하지 마라. unresolved 심볼은 별도 배열로 분리하라.
- 코드 본문을 반환하지 마라. AST 노드 메타만 반환하라.
- vendor/build/generated read deny.
- AstAnalysisResult JSON으로 반환하라.
"""
)
```

두 결과를 `specResult`, `astResult`로 저장.

---

### 3단계: 순차 — analyze-source

```
Task(
  subagent_type="source-code-analyzer",
  model="inherit",
  prompt="""
입력:
{
  "codeRoots": <projectRoot 기반>,
  "targetSymbols": <astResult.testTargets[].fqcn>,
  "buildMetadata": { "buildTool": <buildTool>, "javaVersion": <javaVersion> },
  "lspAvailable": <lspAvailable>
}

지시:
- repo-ast-mcp의 resolve_symbol, parse_java_file을 사용해 호출 그래프를 탐색하라.
- lspAvailable이 true이면 JDT LS를 추가 활용하라.
- 외부 I/O(DB/HTTP/clock/random) testSeam을 식별하라.
- DI 패턴, 트랜잭션 경계, 예외 흐름을 기록하라.
- 대상 심볼 그래프만 탐색하라. vendor/build/generated read deny.
- SourceAnalysisResult JSON으로 반환하라.
"""
)
```

결과를 `sourceResult`로 저장.

---

### 4단계: 순차 — generate-scenarios

```
Task(
  subagent_type="scenario-generator",
  model="inherit",
  prompt="""
입력:
{
  "astResult": <astResult>,
  "sourceResult": <sourceResult>,
  "specResult": <specResult>,
  "testScope": <testScope>
}

지시:
- acceptance criteria(criteriaRefs)와 testSeams를 매핑해 최소 시나리오 집합을 만들라.
- 우선순위: unit(P0) → slice(P1) → integration(P2, slowReason 필수).
- 동치류/경계값 3개 이상 → isParameterized: true.
- 중복은 병합하고 사유를 summary에 기록하라.
- testScope가 "unit"이면 unit만, "mixed"이면 전체 허용.
- ScenarioSet JSON으로 반환하라.
"""
)
```

결과를 `scenarioResult`로 저장.

---

### 5단계: 순차 — generate-tests

```
Task(
  subagent_type="test-code-generator",
  model="inherit",
  prompt="""
입력:
{
  "scenarios": <scenarioResult.scenarios>,
  "buildTool": <buildTool>,
  "junitPolicy": <junitPolicy>,
  "stylePolicy": <stylePolicy>,
  "astResult": <astResult>
}

지시:
- springProfile(Boot 2.0–4.x) 우선 적용: namespace(javax/jakarta), junitEngine(junit4/jupiter), mockAnnotation(@MockBean/@MockitoBean)+정확한 import. springProfile이 없으면 detect_spring_profile로 감지. 전체 템플릿: references/version-compatibility.md.
- 클래스 네이밍: <Target>Test (단위/슬라이스), <Target>IT (통합).
- 메서드 네이밍(필수): <scenarioRefSlug>_<행위> 로 scenarioRef 포함 (SC-001→sc001_...).
- BDD 본문(필수): // given → // when(단일 행위, 결과 캡처) → // then 3단 섹션. 시나리오 given/when/then 1:1 반영. 예외는 // when & then 병합 허용. stub은 BDDMockito given().willReturn()/willThrow().
- 패키지: 대상과 동일 패키지의 src/test/java.
- 컨트롤러 → @WebMvcTest + MockMvc + 협력 빈은 springProfile.mockAnnotation.
- JPA 레포 → @DataJpaTest (junit4면 @RunWith(SpringRunner.class)).
- 서비스/순수 로직 → 스프링 컨텍스트 없는 단위 테스트 (jupiter @ExtendWith(MockitoExtension) / junit4 @RunWith(MockitoJUnitRunner)).
- 다계층 통합 → @SpringBootTest (최소화).
- 협력 빈: springProfile.mockAnnotation을 정확한 import와 함께 사용(임의 고정 금지).
- fixture: <Type>Fixtures/<Type>Builder, 매직값 금지.
- @ParameterizedTest: isParameterized=true인 시나리오 (jupiter). junit4면 Parameterized 또는 데이터 루프.
- @DisplayName: 한국어 행위 서술 (jupiter 한정; junit4는 서술적 메서드명).
- 각 메서드 javadoc에 scenarioRef/criteriaRef 기록.
- Google Java Style, import 완결.
- 실제 네트워크/Thread.sleep/broad catch 금지.
- junitPolicy=strict-5x이면 빌드 파일에 version pin + CHANGELOG 경고 (jupiter 한정).
- unresolved 시그니처는 생성 보류 + warnings 기록.
- TestGenResult JSON으로 반환하라.
"""
)
```

결과를 `genResult`로 저장. `genResult.files[]`를 각 경로에 Write.

---

### 6단계: 순차 — run-tests

```
Task(
  subagent_type="test-runner",
  model="inherit",
  prompt="""
입력:
{
  "buildTool": <buildTool>,
  "task": "미지정",
  "targetScope": <genResult.files[].testClass>
}

지시:
- build-test-mcp의 detect_build_tool, list_test_tasks, run_targeted_tests, parse_junit_xml을 사용하라.
- targetScope 클래스만 실행하라(Gradle: --tests, Maven: -Dtest=).
- 전체 task는 targetScope가 비어 있을 때만 fallback.
- JUnit XML 리포트를 우선 파싱하라.
- 쉘 인자 escaping 필수. 실제 네트워크 호출 금지.
- Write/Edit 도구 사용 금지.
- TestRunResult JSON으로 반환하라.
"""
)
```

결과를 `runResult`로 저장.

---

### 7단계: 조건부 — repair-tests (실패 시에만)

`runResult.failed`가 비어 있으면 7단계를 건너뛴다.

`retryCount = 0`부터 시작해 `maxRepairRetries`에 도달할 때까지 반복한다.

```
Task(
  subagent_type="test-fixer",
  model="inherit",
  prompt="""
입력:
{
  "failResult": <runResult>,
  "originalTests": <genResult.files[].path>,
  "relatedSources": [],
  "retryCount": <retryCount>
}

지시:
- 실패를 유형(TEST_COMPILE_FAILED/TEST_RUNTIME_FAILED/FLAKY_SUSPECTED/SPEC_MISMATCH/SYMBOL_UNRESOLVED)으로 분류하라.
- 최소 diff 수정만 적용하라. 전체 재생성 금지.
- FLAKY_SUSPECTED: Thread.sleep 대신 await/clock 주입 등 결정적 방식 제안.
- SPEC_MISMATCH: spec-doc-mcp로 criteria 재확인 후 assertion 수정.
- SYMBOL_UNRESOLVED: repo-ast-mcp로 시그니처 재확인.
- build-test-mcp.parse_junit_xml로 실패 메시지 정밀 파싱.
- isolation: worktree 환경 전제.
- RepairResult JSON으로 반환하라.
"""
)
```

보정 완료 후 `run-tests`를 `rerunTargets`로 재실행. `retryCount += 1`. `maxRepairRetries` 초과 시 중단.

---

### 8단계: measure-coverage (near-100% 게이트 루프)

테스트가 통과 상태(6/7단계 완료)가 되면 `measure-coverage` 스킬로 JaCoCo 게이트 루프를 돌린다.

```
/spring-test-harness:measure-coverage
```

- build-test-mcp로 JaCoCo 리포트 생성 → `parse_jacoco_report` → `coverage_gate(line,branch,method,class)`.
- 미달 시 `coverage-closer` 에이전트가 `uncovered[]`를 받아 추가 테스트 생성 → `HarnessConfig.maxIterations`까지 재측정.
- 임계값 기본(RESEARCH_NOTES §6): LINE≥0.95 / BRANCH≥0.90 / METHOD≥0.95 / CLASS=1.00, 제외 allowlist 적용.
- 추가된 테스트는 6단계(run-tests)로 회귀 실행해 그린 상태 유지.

결과를 `coverageResult`로 저장.

---

### 9단계: mutation-test (PITest 강화 루프)

커버리지 게이트 통과 후 `mutation-test` 스킬로 테스트 강도를 검증한다.

```
/spring-test-harness:mutation-test
```

- build-test-mcp로 PITest 실행 → `parse_pitest_report` → `mutationScore` / `survivedMutants[]`.
- score < `mutationThreshold`(기본 0.80) 또는 survivor 존재 시 `mutation-analyst`가 단언을 강화해 mutant 제거 → 재실행.
- 금지: Thread.sleep / broad catch / over-mock / 의미 없는 assert. 동등(equivalent) mutant 의심은 보고.

결과를 `mutationResult`로 저장.

---

### 최종 결과 집계 및 반환

모든 단계 결과(`coverageResult`, `mutationResult` 포함)를 수렴해 `PipelineResult` JSON과 Markdown 보고서를 생성한다.

---

## 출력 (PipelineResult)

```json
{
  "status": "ok" | "partial" | "failed",
  "summary": "전체 파이프라인 결과 요약",
  "stages": {
    "ingestSpecs": { "status": "ok", "criteriaCount": 5 },
    "analyzeAst": { "status": "ok", "targetCount": 3 },
    "analyzeSource": { "status": "ok", "seamCount": 4 },
    "generateScenarios": { "status": "ok", "scenarioCount": 8 },
    "generateTests": { "status": "ok", "fileCount": 3 },
    "runTests": { "status": "ok", "passed": 8, "failed": 0 },
    "repairTests": { "status": "skipped" },
    "measureCoverage": { "status": "ok", "line": 0.97, "branch": 0.92, "method": 0.98, "class": 1.00, "gatePassed": true, "iterations": 2 },
    "mutationTest": { "status": "ok", "mutationScore": 0.86, "thresholdMet": true, "iterations": 1 }
  },
  "generatedFiles": [
    "src/test/java/com/example/order/OrderServiceTest.java",
    "src/test/java/com/example/order/OrderControllerTest.java"
  ],
  "reportPaths": [
    "build/test-results/test/TEST-com.example.order.OrderServiceTest.xml"
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
| generate-scenarios | ok | 8개 시나리오 |
| generate-tests | ok | 3개 파일 생성 |
| run-tests | ok | 8/8 통과 |
| repair-tests | 건너뜀 | — |
| measure-coverage | ok | 라인 0.97 / 브랜치 0.92 / 메서드 0.98 / 클래스 1.00 (2회 반복) |
| mutation-test | ok | mutation score 0.86 (목표 0.80 충족) |

## 경고
없음

## 다음 조치
없음
```

---

## 실패 처리 및 중단 조건

| 상황 | 처리 방식 |
|---|---|
| 1·2단계(병렬) 모두 `failed` | 3단계 이후 중단, `status: "failed"` 반환 |
| 1단계만 `failed` | specResult 없이 진행, `status: "partial"` |
| 2단계만 `failed` | `status: "failed"` 반환 (AST 없이 이후 단계 불가) |
| 3단계 `failed` | `status: "failed"` 반환 |
| 4단계 `partial` | 가능한 시나리오로 진행 |
| 5단계 `files` 비어 있음 | `status: "failed"` 반환 |
| 6단계 `BUILD_TOOL_UNDETECTED` | `status: "failed"` 반환 |
| 7단계 `retryCount >= maxRepairRetries` | 미해결 실패 보고, 파이프라인 종료 |
| 8단계 게이트 미달 + `maxIterations` 초과 | `partial`, `remainingGaps[]` + 제외 후보 보고(임의 제외 금지) |
| 9단계 score 미달 + `maxIterations` 초과 | `partial`, `survivingMutants[]` + 동등 mutant 사유 보고 |
| junitPolicy `strict-5x` | `warnings`에 버전 충돌 경고 추가 후 진행 |

보안: 각 단계 subagent는 REPORT.md 권한 모델에 따라 tools/disallowedTools가 제한됨. 쉘 인자 escaping, 네트워크 기본 차단, redaction 필수.
성능: 1·2단계 병렬. 이후 단계는 순차. 대형 저장소는 targets로 스코프를 좁혀 AST 파싱 비용 절감. context 절약을 위해 각 단계 결과는 JSON summary만 메인에 환원.
