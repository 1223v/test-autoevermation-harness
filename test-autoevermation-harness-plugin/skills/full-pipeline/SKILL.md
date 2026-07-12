---
name: full-pipeline
description: Spring 프로젝트에 대해 인터랙티브 설정·스펙 인제스트·AST 분석·소스 분석·시나리오 설계·테스트 생성·실행·보정·커버리지 게이트(near-100%)·뮤테이션 강화까지 end-to-end 파이프라인을 오케스트레이션한다. "스프링 테스트 생성", "하네스 실행", "테스트 파이프라인", "전체 테스트 자동화", "커버리지 100%"처럼 테스트 생성이 필요할 때, 그리고 후속 작업 — "테스트 다시 생성", "재실행", "커버리지 더 올려", "이 패키지만 다시", "결과 개선", "보완", "업데이트", "뮤테이션만 다시" — 처럼 이전 실행을 이어가거나 부분 재실행하는 요청에도 반드시 이 스킬을 사용한다.
---

> **흐름도**: 전체 구동 흐름을 Mermaid로 시각화한 문서는 [docs/pipeline-flow.md](../../docs/pipeline-flow.md) 참조.

## 목적

`HarnessRequest` JSON을 입력받아, 먼저 `configure-harness`로 인터랙티브 설정(`HarnessConfig`)을 받은 뒤, 스킬들(configure-harness, ingest-specs, analyze-ast, analyze-source, refactor-advisory, generate-scenarios, generate-tests, run-tests, repair-tests, measure-coverage, mutation-test, verify-scenarios)을 정해진 순서와 병렬 전략에 따라 오케스트레이션한다. 각 단계의 결과를 수렴해 다음 단계로 전달하고, **near-100% 커버리지 게이트와 뮤테이션 강화 루프**를 수렴시킨 후 **마지막에 시나리오 적합성 검증**까지 마치고 최종 Markdown 보고서와 상태 JSON을 반환한다.

**리팩토링 권고 게이트(3.5단계).** 소스 분석(3단계) 직후, 시나리오 설계(4단계) **전에** 테스트 부적합 코드(순환복잡도 초과·비효율·테스트 저해 설계)를 공식문서 근거로 판정한다. 플래그된 대상은 권고 `.md`(`test_docs/refactoring/RA-*.md`)를 **항상** 작성하고, 대화형은 `AskUserQuestion`으로 "생성 대상 포함/제외"를 묻는다(제외분은 4단계 입력에서 필터링, 권고 문서는 보존). 비대화형·CI는 전 대상 포함+경고. 정본: [references/refactor-advisory.md](../../references/refactor-advisory.md), fallback-policy.md #19.

**시나리오 승인 + 산출물(`test_docs/`).** 시나리오 설계(4단계) 직후, 테스트 생성(5단계) **전에 사용자 승인 게이트**를 둔다 — 시나리오를 대상 프로젝트의 `test_docs/scenarios/<id>.md`로 저장하고, 대화형은 `AskUserQuestion`으로 승인/제외·수정/재설계를 묻는다(승인분만 생성으로 진행). 비대화형·CI는 자동 승인 후 기록. 모든 단계가 끝나면 **마지막 단계(10단계)에서 시나리오 적합성을 검증**해(통과한 테스트가 시나리오 given/when/then을 실제로 만족하는지) `test_docs/`를 **시나리오 ↔ 테스트코드 ↔ 결과**로 정리하고, 불일치(`unmet`)가 있으면 **10.5단계 적합성 자동 보정 루프**(최대 3라운드)로 자동 교정한다. 정본: [references/scenario-docs.md](../../references/scenario-docs.md).

**가장 먼저 Phase E 환경 세팅을 끝낸다.** 0단계 이전에 [references/environment-setup.md](../../references/environment-setup.md)(SSOT) 체크리스트를 TODO로 만들어 환경(역량·빌드도구·프로파일·실행 JDK)을 **선제적으로 전부 세팅**한다 — fallback을 파이프라인 도중에 마주치기 전에 제거한다. 여기에 **대상 빌드 능력(JaCoCo XML·PITest 플러그인)과 의존성 캐시 프라이밍**(0.6단계, E11·E12)이 포함된다 — 미비 시 커버리지/뮤테이션(8·9단계)·첫 실행(6단계)이 깨지므로 `detect→approve→inject`로 선제 처리한다([references/build-provisioning.md](../../references/build-provisioning.md)). 자동으로 고칠 수 있는 항목은 **대화형=항목별 `AskUserQuestion` 후 함께 세팅 / 비대화형·CI=자동 세팅**(`pip install`·`mvn package`). 미충족 잔여 항목이 있으면 파이프라인을 **시작하지 않는다**. 런타임 의사결정 fallback은 [references/fallback-policy.md](../../references/fallback-policy.md)(SSOT)를 따른다 — **대화형은 `AskUserQuestion`, 비대화형은 결정적 항목 자동 세팅·그 외 하드 중단**(remediation 안내).

---

## 실행 모드 · `_workspace/` · 부분 재실행 (성능)

**실행 모드: 서브에이전트 팬아웃/파이프라인.** 1·2단계는 상호 통신이 불필요한 독립 작업이므로 `Task(subagent_type=...)` 병렬 호출을 쓴다(에이전트 팀의 `TeamCreate`/`SendMessage` 조율 비용·지연을 피함). 이후는 순차 의존이라 파이프라인으로 잇는다.

**`_workspace/` 파일 기반 전달.** 각 단계 산출물(JSON)을 메인 컨텍스트로 통째로 옮기지 말고 `_workspace/{단계}_{에이전트}_{산출물}.json`에 저장하고, 다음 단계에는 **경로만** 전달한다. 메인 컨텍스트에는 `{status, 핵심수치, 경로}` 요약만 환원한다 → 컨텍스트 토큰 절감.

**Phase 0 컨텍스트 확인(부분 재실행 · 상태 복원).** 시작 시 `_workspace/` 존재와 요청 유형으로 실행 범위를 정한다. `_workspace/`는 `.gitignore` 대상(휘발성)이지만 **영속 증거**(생성 테스트 `src/test/java`, 승인 시나리오 `test_docs/scenarios/*.md`, JaCoCo/JUnit/PITest 리포트)는 커밋되어 살아남으므로, `_workspace/`가 없거나 불완전해도 **결정적으로 상태를 복원**해 알맞은 단계부터 재개한다:

- `_workspace/` **존재** + 부분 요청(예: "이 패키지만", "커버리지만 다시", "뮤테이션만") → **부분 재실행**: 영향 단계만 재호출하고 나머지는 `_workspace/`의 기존 산출물을 Read로 재사용 → 전체 재실행 회피(매트릭스: [references/orchestration-detail.md](references/orchestration-detail.md) §3).
- `_workspace/` **부재 또는 불완전** → **`mcp__plugin_test-autoevermation-harness-plugin_build-test__detect_pipeline_state(root=projectRoot)` 호출**로 영속 증거를 물리 판정한다(LLM 눈대중 금지). **이 도구가 세션에 노출되어 있지 않으면 설치본이 v0.20.0 미만(구버전)이라는 신호다** — Grep/Read 눈대중 복원으로 대체하지 말고 #20 준용으로 중단하고, remediation으로 플러그인 업데이트(`/plugin` 재설치 후 재시작) 후 재시도를 안내한다. **핵심 구분: `harnessProvenance`** — 테스트 파일이 있어도 그게 *이 하네스가 생성한 것*(=`test_docs/` 존재)인지, *원래 프로젝트에 손으로 짠 것*(foreign)인지를 판정한다(도구가 `harnessProvenance`·`foreignTestsPresent`로 반환):
  - `resumable:false` + `foreignTestsPresent:false`(영속 증거 없음) → **초기 실행**(0단계부터 전체).
  - `resumable:false` + `foreignTestsPresent:true`(**기존 손수 짠 테스트만 있고 하네스 흔적 없음**) → **초기 실행(0단계부터)** — 단, 기존 테스트를 "5단계 완료"로 보지 않고 정식으로 시나리오 설계·테스트 생성을 진행한다. 감지된 `testFiles[]`를 **8단계 coverage-closer의 `existingTestPaths` 입력**으로 전달해 기존 테스트와 **공존하며 커버리지 갭만 보완**하고, 5단계 generate-tests는 자체 규칙(기존 파일 덮어쓰기 전 확인·동일 경로 충돌 시 내용 비교, generate-tests/SKILL.md·test-code-generator)으로 손수 짠 테스트를 덮어쓰지 않는다. `_resume.json`·`05` stub은 쓰지 않는다(재개가 아님). 대화형은 "신규 생성(기존 공존)"임을 안내한다.
  - `resumable:true`(**하네스가 생성한** 테스트/승인 시나리오 존재 = `harnessProvenance:true`) → **상태 복원**: 감지 결과로 `_workspace/`에 최소 stub 산출물을 재구성하고([orchestration-detail.md](references/orchestration-detail.md) §2 "영속 증거 → stub 복원 표"), `_workspace/_resume.json`(`{entryStage, entryLabel, ts}`)을 기록한 뒤 **재진입 단계를 확정**:
    - **대화형**: 복원 요약(`hasTests`·`scenarios.approved`·`jacocoReport`·`pitestReport`)을 제시하고 `AskUserQuestion`으로 재진입 단계를 `[6 run-tests] [8 measure-coverage] [9 mutation-test] [4 시나리오 재설계]` 중 선택하게 한다.
    - **비대화형·CI**: 질문 없이 `recommendedEntryStage`를 사용한다 — 기본값은 기존 하네스 테스트를 5단계 완료로 간주해 **6(run)→8(coverage)→9(mutation)→10(conformance)**(재생성 없이 측정·강화·보정). 승인 시나리오만 있고 테스트가 없으면 5단계부터. fallback-policy CI 자동 원칙 준수.
  - 재진입 후에는 해당 stub 경로를 하위 스킬 프롬프트에 전달해 "기존 결과를 읽고 변경분만 반영"하게 한다(전량 재생성 금지). 최종 집계 전까지 `pipeline_result.json`을 쓰지 않는다(복원은 "완료"가 아니라 "재개").
- `_workspace/` **존재** + 새 입력 → **새 실행**: 기존 `_workspace/`를 `_workspace_{YYYYMMDD_HHMMSS}/`로 이동 후 초기 실행.

**단계별 계측(timing.json).** 각 서브에이전트 완료 알림의 `total_tokens`/`duration_ms`는 **그 시점에만** 접근 가능하므로 즉시 `_workspace/timing.json`에 누적 저장한다(느린·비싼 단계 식별용). 헬퍼: `scripts/record-timing.py`.

> 전체 규약(부분 재실행 매트릭스·데이터 전달 표·에러 핸들링·timing 스키마)은 필요할 때만 로드: [references/orchestration-detail.md](references/orchestration-detail.md).

---

## 자동 호출 조건

- 사용자가 "스프링 테스트 생성", "하네스 실행", "테스트 파이프라인", "전체 테스트 자동화", "테스트 하네스 돌려줘"와 같은 키워드를 사용할 때
- CI에서 `claude -p --output-format json`으로 직접 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:full-pipeline
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
  "lspAvailable": true,
  "maxRepairRetries": 3
}
```

---

## 입력 (HarnessRequest)

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `projectRoot` | `string` | 아니오 | `"미지정"` → 0단계 #13 질문/중단 (자동 cwd 금지) | Spring 프로젝트 루트 경로 |
| `specDocPaths` | `string[]` | 아니오 | `[]` → 계속 여부 질문(#10)/중단 | 스펙 문서 경로 목록 |
| `targets` | `string[]` | 아니오 | `[]` → 0단계 #13 확정 (detect는 후보 제시용) | 분석 대상 패키지 또는 FQCN |
| `targetModules` | `string[]` | 아니오 | `[]` → 0단계 #13 확정 (detect는 후보 제시용) | 멀티 모듈 대상 |
| `buildTool` | `string` | 아니오 | `"미지정"` → 0단계 #5·#13 확정 | `gradle` 또는 `maven` |
| `junitPolicy` | `string` | 아니오 | `"jupiter-style"` | `jupiter-style`(BOM 위임) 또는 `strict-5x` |
| `testScope` | `string` | 아니오 | `"mixed"` | `unit` / `slice` / `integration` / `mixed` |
| `javaVersion` | `string` | 아니오 | `"미지정"` → 0단계 #13 확정 | `17`–`26` |
| `springVersion` | `string` | 아니오 | `"미지정"` → 0단계 #4·#13 확정 | Spring Boot 버전 (예: `3.4.5`) |
| `stylePolicy` | `string` | 아니오 | `"google-java"` | 코드 스타일 정책 |
| `lspAvailable` | `boolean` | 아니오 | `true` | JDT LS 연결 여부. E7(JDT LS)은 Phase E 필수 항목이므로 통과 시 항상 `true` — 미가용이면 Phase E에서 하드 중단 |
| `maxRepairRetries` | `integer` | 아니오 | `3` | repair-tests **진전 추적 단위**(고정 상한 아님 — #12 무진전 판정 기준 "동일 실패 3회 연속"과 정렬) |
| `domainKeywords` | `string[]` | 아니오 | `[]` | 스펙 검색 힌트 |
| `refactorAdvisory` | `object` | 아니오 | `{ "enabled": true }` | 3.5단계 제어. `enabled`·`thresholds{cyclomatic,constructorArgs}` — 정본: [refactor-advisory.md](../../references/refactor-advisory.md) §5 |

### 미지정 필드 처리 원칙 (fallback-policy.md #13 — 자동 기본값 금지)

미지정 필드는 **auto-detect/기본값으로 자동 채우지 않는다.** `configure-harness`가 대화형이면 `AskUserQuestion`으로 질문, CI면 하드 중단한다. (detect_* 도구는 후보 제시용으로만 쓰고, 확정은 사용자 질문/명시값으로 한다.)

- `projectRoot: "미지정"` → 질문(대화형) / 중단(CI). 자동 cwd 사용 안 함
- `specDocPaths: []` → 계속할지 질문(#10, 대화형) / 중단(CI)
- `targets: []` → "직접 지정 / 자동 탐지" 질문 후 확정(자동 탐지는 사용자가 명시 선택한 경우만)
- `buildTool: "미지정"` → `detect_build_tool` 후보 제시 + 질문(#5). 미감지·미확정이면 중단(CI)
- `javaVersion: "미지정"` → `springProfile.javaBaseline` 후보 제시 + 질문 / 중단(CI)
- `springVersion: "미지정"` → `detect_spring_profile`. `interviewRequired`면 대화형=Boot major 질문 / CI=중단(#4). `requiresConfirmation`이면 충돌 확정 질문(#6). 가정 금지. 이 프로파일이 모든 관용구(javax/jakarta, junit4/jupiter, @MockBean/@MockitoBean)를 결정(RESEARCH_NOTES §8)
- `junitPolicy: "strict-5x"` → 빌드 파일에 version pin + CHANGELOG 경고 추가

---

## 단계별 절차

### 전처리: 입력 정규화

**설계 기본값이 있는 필드만** 아래 값으로 채운다. `"미지정"`/`[]` 플레이스홀더는 값을 "채운" 것이 아니라 **0단계 configure-harness가 #13(질문/중단)으로 확정해야 하는 미확정 신호**다 — 전처리에서 cwd·auto-detect로 대신 채우지 않는다.

```
projectRoot       = 입력값 또는 "미지정"   # 자동 cwd 채움 금지(#13) — 0단계에서 질문/중단으로 확정
specDocPaths      = 입력값 또는 []
targets           = 입력값 또는 []
targetModules     = 입력값 또는 []
buildTool         = 입력값 또는 "미지정"
junitPolicy       = 입력값 또는 "jupiter-style"
testScope         = 입력값 또는 "mixed"
javaVersion       = 입력값 또는 "미지정"
springVersion     = 입력값 또는 "미지정"
stylePolicy       = 입력값 또는 "google-java"
lspAvailable      = 입력값 또는 configure-harness E7 통과값(Phase E 통과 시 항상 true — E7은 필수 항목이며, 미가용이면 Phase E에서 하드 중단하므로 false로 이 단계에 도달하지 않는다)
maxRepairRetries  = 입력값 또는 3   # 진전 추적 단위(#12 무진전 3회 연속과 정렬)
domainKeywords    = 입력값 또는 []
refactorAdvisory  = 입력값 또는 { "enabled": true }  (thresholds 미지정 시 refactor-advisory.md §2 기본값;
                    병합 순서: HarnessConfig.refactorAdvisory(0단계 산출) > HarnessRequest 입력값 > 기본값)
```

`junitPolicy: "strict-5x"` 감지 시 `warnings`에 "BOM 기본값(Jupiter 6.0.x)과의 버전 충돌 주의 — 명시적 version pin 필요" 추가.

---

### Phase E: 환경 세팅 (0단계 이전 — 선행 필수)

전처리 직후, 0단계 진입 **전에** `configure-harness`를 호출해 Phase E 체크리스트(E1~E10)를 통과시킨다. **수행 주체는 configure-harness다** — 항목별 감지·세팅 명령·대화형/CI 분기의 실행 절차는 그 스킬의 Preflight 절이, 항목 정의·통과 기준·degrade 금지 원칙은 [references/environment-setup.md](../../references/environment-setup.md)(SSOT)와 fallback-policy #2·#3·#20이 정본이다(여기 재열거하지 않는다).

이 오케스트레이터는 절차를 재수행하지 않고 **산출물로만 판정**한다: 이미 통과한 `_workspace/00_config-harness.json`이 있으면 재사용(중복 실행 금지), 없으면 configure-harness 호출, 필수 항목 미충족이면 0단계로 진행하지 않고 `status:"failed"` + remediation으로 중단.

- E8 빌드도구·E9 Spring 프로파일은 0.5단계, **E11 빌드 능력(JaCoCo XML·PITest)·E12 의존성 캐시 프라이밍은 0.6단계**에서 확정 — 6단계 run-tests 이전 필수([references/build-provisioning.md](../../references/build-provisioning.md)).

---

### 0단계: configure-harness (인터랙티브 설정)

대화형 CLI에서는 `configure-harness` 스킬로 사용자에게 4항목(스펙 경로 추가 / 대상 폴더·패키지 선별 / 뮤테이션 깊이·대상 / 커버리지 임계값·제외)을 AskUserQuestion으로 질문하고 `HarnessConfig`를 만든다. 비대화형(`claude -p`/CI)에서는 인터뷰를 건너뛰고 `HarnessRequest` + RESEARCH_NOTES §6 기본값으로 `HarnessConfig`를 구성한다.

```
/test-autoevermation-harness-plugin:configure-harness
```

산출 `HarnessConfig`는 `specDocPaths`(추가 병합), `targets`/`targetModules`(대상 스코프 — 8단계에서 measure-coverage의 `targetScope` 입력으로 매핑), `coverage{line,branch,method,class,excludes}`, `mutation{targetClasses,targetTests,mutators,mutationThreshold}`, `coverageMaxIterations`/`mutationMaxIterations`(8·9단계 `maxIterations`로 매핑), `refactorAdvisory{enabled,thresholds}`(3.5단계 제어, 인터뷰 항목 아님)를 포함하며, 이후 모든 단계의 입력에 병합된다. 사용자가 재사용 가능한 도메인 특화 단계를 원하면 configure-harness가 `skills/<custom>/SKILL.md`를 그 자리에서 스캐폴드하고 `/test-autoevermation-harness-plugin:<custom>`로 호출 가능하게 한다.

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
  "buildMetadata": { "buildTool": <buildTool>, "javaVersion": <javaVersion>, "springBootVersion": <springProfile.bootVersion> },
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

### 3.5단계: 리팩토링 권고 게이트 (선(先) 권고 기록, 후(後) 대상 확정)

`sourceResult`를 받은 직후, 4단계(시나리오 설계) **전에** 테스트 부적합 코드를 판정하고 사용자 결정을 받는다. 정본: [references/refactor-advisory.md](../../references/refactor-advisory.md). `refactorAdvisory.enabled: false`면 이 단계 전체를 건너뛴다(3→4 직결, 보고서에 `skipped` 명시).

1. **판정** — `refactor-advisor` 호출:

```
Task(
  subagent_type="refactor-advisor",
  model="inherit",
  prompt="""
입력:
{
  "astResult": <astResult>,
  "sourceResult": <sourceResult>,
  "targetSymbols": <astResult.testTargets[].fqcn>,
  "projectRoot": <projectRoot>,
  "lspAvailable": <lspAvailable>,
  "thresholds": <refactorAdvisory.thresholds>
}

지시:
- references/refactor-advisory.md §2의 3범주(complexity/testability/efficiency) 기준·임계값·근거 출처로만 판정하라(임의 수치 금지).
- 대상 심볼과 직접 협력 객체(1홉)의 소스만 Read/Grep하라. repo-ast는 메타 확인용(메서드 바디 미반환).
- sourceResult.testSeams·collaborators를 재사용해 이중 파싱을 피하라.
- 임계 미달·근거 부족 발견은 플래그하지 마라(허위 양성 억제).
- 소스 원문을 결과에 넣지 마라. 경로·라인·지표만.
- RefactorAdvisoryResult JSON으로 반환하라.
"""
)
```

결과를 `advisoryResult`로 저장(`_workspace/03b_refactor_advisory.json`). **`advisories`가 0건이면 게이트를 생략**하고 4단계로 직행한다(기존 3→4 흐름과 동일).

2. **선(先) 기록**: 각 advisory를 `<projectRoot>/test_docs/refactoring/RA-<id>.md`(frontmatter `decision: pending`)로 Write하고, `refactoring/INDEX.md`와 메인 `test_docs/INDEX.md`의 "## 리팩토링 권고" 요약 절을 갱신한다. 템플릿: refactor-advisory.md §3. 권고 `.md`는 **포함/제외 결정과 무관하게 항상 작성**한다(침묵 누락 금지).
3. **결정 게이트** (fallback-policy.md #19):
   - **대화형**: 권고 요약(대상·범주·severity 표)을 제시하고 `AskUserQuestion`으로 묻는다 — `전체 포함(권장)` / `일부 제외` / `전체 제외` (4.5 게이트의 3옵션 패턴 미러 — AskUserQuestion 옵션 수 제한으로 대상별 나열 금지).
     - `일부 제외`: 후속 자유 입력으로 제외할 `RA-id`를 받는다.
   - **비대화형·CI**: **전 대상 포함 + `warnings` 기록**(권고 `.md`는 그대로 작성).
4. **반영**: 포함분 `decision: included`, 제외분 `decision: excluded`(+`decidedAt`, 사유)로 frontmatter 갱신(파일 삭제 금지 — 추적성 보존). 결과를 `_workspace/03c_advisory_gate.json`에 저장한다.
5. **필터**: 제외 대상 FQCN을 `astResult.testTargets`·`sourceResult`(collaborators/testSeams 등 대상 종속 항목)에서 제거한 **필터본을 이후 단계 입력으로** 쓴다. **전 대상 제외로 포함이 0건이면** 4.5의 "승인 0건"에 준해 `status: "partial"` + "생성 대상 없음(전량 리팩토링 권고)" 보고 후 중단한다.

포함된 대상의 시나리오·테스트가 생성되면(4~5단계 이후) 해당 `RA-*.md`의 "추적성" 절에 SC-id·테스트 메서드를 기록한다.

---

### 4단계: 순차 — generate-scenarios

> `astResult`·`sourceResult`는 **3.5단계 게이트에서 제외 대상이 필터링된 버전**을 전달한다(플래그 0건·skip이면 원본 그대로).

```
Task(
  subagent_type="scenario-generator",
  model="inherit",
  prompt="""
입력:
{
  "astResult": <astResult의 {testTargets, riskPoints} 서브셋 — 시나리오 설계가 참조하는 필드만 전달(전체 객체 전달 금지, 토큰 절감)>,
  "sourceResult": <sourceResult의 {testSeams, collaborators, exceptionFlows, externalDependencies} 서브셋>,
  "specResult": <specResult의 {acceptanceCriteria} 서브셋>,
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

### 4.5단계: 시나리오 승인 게이트 + `test_docs/` 저장 (선(先) 승인, 후(後) 생성)

`scenarioResult`를 받은 직후, 5단계(생성) **전에** 시나리오를 영속화하고 사용자 승인을 받는다. 정본: [references/scenario-docs.md](../../references/scenario-docs.md) §3.

1. **선(先) 기록**: 각 시나리오를 `<projectRoot>/test_docs/scenarios/<id>.md`(frontmatter `approval: pending`)로 Write하고, `<projectRoot>/test_docs/INDEX.md`(시나리오↔테스트코드↔결과 표, 이 시점엔 매핑/결과 미정)를 갱신한다. 템플릿은 scenario-docs.md §2.
2. **승인 게이트** (fallback-policy.md #15):
   - **대화형**: 시나리오 요약(유형별 개수·목록)을 제시하고 `AskUserQuestion`으로 묻는다 — `전체 승인` / `일부 제외·수정` / `재설계 요청`.
     - `일부 제외·수정`: 제외/수정할 `id`를 받아 해당 파일을 `approval: excluded`로 갱신.
     - `재설계 요청`: 사유를 받아 4단계를 재호출(부분 재실행). 무진전 판정은 #12 준용.
   - **비대화형·CI**: 전체 `approved`로 자동 승인하고 진행(기록만 남김).
3. **반영**: 승인분만 `approval: approved`로 갱신하고, **승인된 시나리오 집합(`approvedScenarios`)만** 5단계 입력으로 넘긴다. 제외분은 `excluded`로 보존(파일 삭제 금지).
4. 승인/제외 결과를 `_workspace/04b_approval.json`에 저장한다.

> `test_docs/`는 **대상 프로젝트 루트**(`projectRoot`) 아래에 만든다(플러그인 저장소 아님). 사람이 읽는 영속 산출물이므로 `_workspace/`와 달리 ignore 대상이 아니다.

---

### 5단계: 순차 — generate-tests

```
Task(
  subagent_type="test-code-generator",
  model="inherit",
  prompt="""
입력:
{
  "scenarios": <approvedScenarios>,
  "buildTool": <buildTool>,
  "junitPolicy": <junitPolicy>,
  "stylePolicy": <stylePolicy>,
  "astResult": <astResult>,
  "springProfile": <springProfile (0단계 configure-harness 산출 — 인터뷰로 확정된 프로파일을 그대로 전달)>,
  "projectRoot": <projectRoot>,
  "testSourceRoot": <{projectRoot}/src/test/java>
}

지시:
- 생성 규칙 전체(클래스·메서드 네이밍, BDD 3단 본문, slice 선택 기준, Mockito/MockMvc, fixture, 스타일, 금지 패턴)는
  **네 자신의 에이전트 정의(agents/test-code-generator.md)와 references/test-code-invariants.md가 정본**이다 — 그대로 따르라(여기 재서술하지 않음).
- springProfile(Boot 2.0–4.x) 우선 적용 — 입력에 없으면 detect_spring_profile로 감지(references/version-compatibility.md).
- junitPolicy=strict-5x이면 빌드 파일에 version pin + CHANGELOG 경고 (jupiter 한정).
- unresolved 시그니처는 생성 보류 + warnings 기록.
- 시나리오 target 호출 자가 검증(필수 게이트): 각 파일 기록 후 parse_java_file의 methodCalls로 대조해
  모든 files[] 항목에 targetCallCheck를 기록하라 — unit 기계 대조 → "matched" / slice 체크리스트 → "manual-verified" /
  1회 자가 수정 후에도 불일치 → 파일 제외(기록했다면 삭제) + warnings에 SCENARIO_TARGET_MISMATCH.
- TestGenResult JSON으로 반환하라(files[].testClass 필수 — 6단계 실행 스코프 입력).
"""
)
```

결과를 `genResult`로 저장. **파일 기록은 test-code-generator가 자가 검증 게이트(기록→parse→대조) 수행 과정에서 이미 완료했다 — 오케스트레이터가 `files[].content`로 다시 Write하지 않는다(이중 기록 금지, 소유권은 에이전트).** 오케스트레이터는 `files[]`의 `targetCallCheck`만 검사한다: 없거나 `"mismatch"`인 항목은 디스크에서 삭제·결과에서 제외하고 `warnings`(`SCENARIO_TARGET_MISMATCH`)로 보고한다 — 필드 누락은 게이트 미수행으로 간주한다(별도 5.5단계 없이 이 필드 검사로 게이트를 강제한다).

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
  "targetScope": { "classes": <genResult.files[].testClass>, "packages": [], "methods": [] },
  "projectRoot": <projectRoot>
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

> **콜드 캐시 프라이밍(#18)**: 0.6단계 `check_dependency_cache`가 `primed:false`였고 사용자가 승인했다면, **첫 run-tests만** `run_targeted_tests(online=True)`로 1회 온라인 실행(또는 Maven `dependency:go-offline` 선행)하고 이후 호출은 오프라인 유지한다. 0.6단계에서 JaCoCo XML/PITest 플러그인을 새로 주입(#17)한 경우에도 1회 프라이밍이 필요하다. 근거: Gradle `--offline`은 미캐시 모듈 시 빌드 실패([build-provisioning.md](../../references/build-provisioning.md) §2).

---

### 7단계: 조건부 — repair-tests (실패 시에만)

`runResult.failed`가 비어 있으면 7단계를 건너뛴다.

`retryCount = 0`부터 시작해 **그린이 될 때까지** 반복한다 — `maxRepairRetries`는 진전 추적 단위일 뿐 고정 상한이 아니다(fallback-policy.md #12).

```
Task(
  subagent_type="test-fixer",
  model="inherit",
  prompt="""
입력:
{
  "failResult": <runResult>,
  "originalTests": <genResult.files[].path>,
  "relatedSources": <astResult.testTargets[]에서 실패 테스트의 대상 FQCN에 해당하는 {path: <testTargets[].file>, fqcn} 목록 — 경로 출처는 repo-ast가 반환한 file 필드(AstAnalysisResult.testTargets[].file)다. sourceResult(collaborators)는 fqcn만 있고 경로 필드가 없으므로 경로 출처로 쓰지 않는다>,
  "springProfile": <springProfile (0단계 configure-harness 산출)>,
  "scenarioDocs": <실패 테스트의 scenarioRef에 해당하는 test_docs/scenarios/<id>.md 경로 목록>,
  "retryCount": <retryCount>
}

지시:
- 실패를 유형(TEST_COMPILE_FAILED/TEST_RUNTIME_FAILED/FLAKY_SUSPECTED/SPEC_MISMATCH/SYMBOL_UNRESOLVED)으로 분류하라.
- 최소 diff 수정만 적용하라. 전체 재생성 금지.
- 수정 시 생성 불변식(BDD 3단 구조·BDDMockito 스타일·scenarioRef 보존·springProfile 관용구·단언 완화 금지)은 references/test-code-invariants.md를 그대로 따르라.
- FLAKY_SUSPECTED: Thread.sleep 대신 await/clock 주입 등 결정적 방식 제안.
- SPEC_MISMATCH: spec-doc-mcp로 criteria 재확인 후 assertion 수정(scenarioDocs의 given/when/then 대조).
- SYMBOL_UNRESOLVED: repo-ast-mcp로 시그니처 재확인.
- build-test-mcp.parse_junit_xml로 실패 메시지 정밀 파싱.
- isolation: worktree 환경 전제.
- RepairResult JSON으로 반환하라.
"""
)
```

**패치 반영**: `test-fixer`는 `isolation: worktree`로 격리 실행되므로 worktree 안의 수정은 메인 작업 트리에 반영되지 않는다. 반환된 `patches[]`의 각 unified diff를 **메인 트리의 대응 파일에 적용**한다 — `path`가 worktree 절대경로면 프로젝트 상대경로로 재매핑하고, diff의 변경 hunk를 Edit(old→new 치환)으로 옮긴다. 적용 결과를 `_workspace/07_repair_result.json`에 저장한 뒤, `run-tests`를 `rerunTargets`로 재실행한다. 반복·무진전 중단 규칙은 7단계 서두와 동일하다(#12 — 여기 재정의하지 않음).

---

### 8단계: measure-coverage (near-100% 게이트 루프)

테스트가 통과 상태(6/7단계 완료)가 되면 `measure-coverage` 스킬로 JaCoCo 게이트 루프를 돌린다. **HarnessConfig를 명시적으로 매핑해 전달한다** — 스킬 호출만 하고 입력을 생략하면 임계값·제외·스코프·프로파일이 기본값으로 떨어진다.

```
/test-autoevermation-harness-plugin:measure-coverage
```

입력(HarnessConfig 매핑):
```json
{
  "buildTool": <buildTool>,
  "root": <projectRoot>,
  "coverage": <HarnessConfig.coverage (임계값 4종 + excludes)>,
  "maxIterations": <HarnessConfig.coverageMaxIterations>,
  "targetScope": <HarnessConfig.targets + targetModules 매핑>,
  "springProfile": <springProfile>,
  "junitPolicy": <junitPolicy>,
  "stylePolicy": <stylePolicy>,
  "existingTestPaths": <genResult.files[].path>
}
```

- build-test-mcp로 JaCoCo 리포트 생성 → `parse_jacoco_report` → `coverage_gate(root, line, branch, method, klass, mutation)`(서버 파라미터명은 `klass` — `class`는 파이썬 예약어). 8단계는 `require_pitest`를 생략(기본 False — 뮤테이션 이전이라 PITest 리포트 부재가 정상, 부재를 partial 사유로 삼지 않음). 9단계 이후 종합 확인만 `require_pitest=True`.
- 미달 시 `coverage-closer` 에이전트가 `uncovered[]`를 받아 추가 테스트 생성 → 게이트 충족까지 재측정(fallback-policy.md #12: 진전 있는 한 계속, 동일 미커버 집합 3회 연속이면 무진전으로 보고 후 중단).
- 임계값 기본(RESEARCH_NOTES §6): LINE≥0.95 / BRANCH≥0.90 / METHOD≥0.95 / CLASS=1.00, 제외 allowlist 적용.
- **회귀 실행 + runResult 재할당**: 게이트 수렴 후 `coverageResult.addedTests`가 있으면 6단계(run-tests)를 생성+추가 테스트 전체로 회귀 실행해 그린 상태를 확인하고(실패 시 7단계 보정 루프 재진입), 그 결과를 **`runResult`로 재할당**한다 — 10단계는 이 최신 값을 받는다.
- **스킵 금지 + 산출물 유효성 (#21)**: [fallback-policy.md #21](../../references/fallback-policy.md)을 그대로 따른다 — RA advisory는 스킵 사유가 아니며, 무효 산출물(`gatePassed:false`∧루프 증거 없음)이면 9단계로 진행하지 말고 8단계를 재실행한다(`guard-gate-artifacts.py` 훅이 무효 기록을 차단).

결과를 `coverageResult`로 저장.

---

### 9단계: mutation-test (PITest 강화 루프)

커버리지 게이트 통과 후 `mutation-test` 스킬로 테스트 강도를 검증한다. 8단계와 마찬가지로 **HarnessConfig를 명시적으로 매핑해 전달한다**.

```
/test-autoevermation-harness-plugin:mutation-test
```

입력(HarnessConfig 매핑):
```json
{
  "buildTool": <buildTool>,
  "root": <projectRoot>,
  "mutation": <HarnessConfig.mutation (targetClasses/targetTests/mutators/mutationThreshold/threads)>,
  "maxIterations": <HarnessConfig.mutationMaxIterations>,
  "springProfile": <springProfile>,
  "junitPolicy": <junitPolicy>,
  "stylePolicy": <stylePolicy>,
  "existingTestPaths": <genResult.files[].path + coverageResult.addedTests 병합>
}
```

- build-test-mcp로 PITest 실행 → `parse_pitest_report` → `mutationScore` / `survivedMutants[]`.
- score < `mutationThreshold`(기본 0.80) 또는 survivor 존재 시 `mutation-analyst`가 단언을 강화해 mutant 제거 → 재실행.
- 금지: Thread.sleep / broad catch / over-mock / 의미 없는 assert. 동등(equivalent) mutant 의심은 보고.
- **회귀 실행 + runResult 재할당**: 뮤테이션 루프 수렴 후(단언 강화·테스트 추가가 1회라도 있었으면) 6단계(run-tests)를 전체 대상(생성+추가 테스트)으로 회귀 실행한다. 강화된 단언이 실패하면 7단계 보정 루프로 재진입하고, 최종 그린 결과를 **`runResult`로 재할당**한다 — 이것이 10단계에 전달되는 최종 실행 결과다. 이 회귀가 없으면 9단계에서 바뀐 테스트의 실행 상태가 10단계에 stale로 전달된다.
- **스킵 금지 + 산출물 유효성 (#21)**: [fallback-policy.md #21](../../references/fallback-policy.md)을 그대로 따른다 — RA advisory는 스킵 사유가 아니며, 무효 산출물(`thresholdMet:false`∧루프 증거 없음)이면 10단계로 진행하지 말고 9단계를 재실행한다(훅이 무효 기록을 차단).

결과를 `mutationResult`로 저장.

---

### 10단계: verify-scenarios (시나리오 적합성 검증 — 마지막)

모든 단계(생성·실행·커버리지·뮤테이션)가 끝나면 `verify-scenarios` 스킬로 **승인된 각 시나리오가 실제로 충족되었는지** 검증한다. 단순 통과 여부가 아니라, 통과한 테스트가 시나리오의 given/when/then을 만족하는지 확인하고 `test_docs/`를 시나리오↔테스트코드↔결과로 정리한다. 정본: [references/scenario-docs.md](../../references/scenario-docs.md) §4.

```
/test-autoevermation-harness-plugin:verify-scenarios
```

```
Task(
  subagent_type="scenario-conformance-verifier",
  model="inherit",
  prompt="""
입력:
{
  "approvedScenarios": <approvedScenarios>,
  "generatedFiles": <genResult.files[].path + coverageResult.addedTests 병합 (8단계 gap-filling 테스트 포함)>,
  "runResult": <runResult (최종 — 7단계 보정 및 8·9단계 회귀 실행 이후 재할당된 값)>,
  "coverageResult": <coverageResult>,
  "projectRoot": <projectRoot>,
  "testDocsDir": "test_docs"
}

지시:
- scenarioRef(메서드명 sc001_… + javadoc scenarioRef/criteriaRef)로 시나리오 → 테스트 메서드를 매핑하라.
- target 호출 기계 대조: parse_java_file의 methodCalls로, unit/직접호출 시나리오는 시나리오 target(FQCN#method)의
  메서드 단순명이 매핑 테스트 메서드의 호출 목록에 있는지 기계 판정하라(없으면 결정적 unsatisfied +
  nonconformanceClass: WRONG_TARGET_CALL). slice는 when의 HTTP verb/경로 ↔ perform(...) 및 given stub 메서드명 대조.
- satisfied(매핑+통과+target 호출 일치+then 단언 충족) / unsatisfied(매핑되나 실패·target 불일치·단언 부족) / missing(매핑 없음)으로 판정하라.
- unsatisfied/missing에는 nonconformanceClass(WRONG_TARGET_CALL/THEN_GAP/GIVEN_MISMATCH/MAPPING_MISSING)를 반드시 기록하라(10.5단계 라우팅 힌트).
- // then 단언이 시나리오 then을 빠짐없이 반영하는지 테스트 본문과 대조해 판정하라(thenCovered 충족/전체).
- test_docs/scenarios/<id>.md의 "테스트 코드 매핑"·"검증 결과" 섹션과 INDEX.md를 갱신하라(references/scenario-docs.md §2).
- 테스트 코드를 새로 생성/수정하지 마라(검증·문서화 전용). 소스 원문·민감정보 기록 금지.
- ConformanceResult JSON으로 반환하라.
"""
)
```

결과를 `conformanceResult`로 저장하고 `_workspace/10_conformance.json`에 보존한다.

**게이트 (fallback-policy.md #16)**: `unmet`(unsatisfied/missing)이 하나라도 있으면 **10.5단계 적합성 자동 보정 루프로 진입한다**(대화형·CI 동일 — 사용자에게 먼저 묻지 않는다). 전부 satisfied면 10.5단계를 건너뛰고 `ok`. 임의 제외·무시 금지.

---

### 10.5단계: 조건부 — 적합성 자동 보정 루프 (unmet 존재 시)

10단계가 발견한 불일치를 **보고로 끝내지 않고** 자동 보정한다. 통과했지만 시나리오와 어긋난 테스트(예: target `recordMoResult` 대신 유사명 `recordMtResult` 호출)는 6·7단계가 잡을 수 없으므로(7단계는 실패 테스트만 보정) 이 루프가 유일한 자동 교정 경로다.

```
round = 1..3 (하드 캡):
  1. conformanceResult.unmet을 verdict별로 분할:
     - unsatisfied → test-fixer 호출(모드 B — SCENARIO_NONCONFORMANT): 입력에 nonconformantItems[]
       (scenarioResults에서 unsatisfied 항목의 scenarioId/testClass/testMethods/verdict/
       nonconformanceClass/notes), originalTests, relatedSources, springProfile, scenarioDocs를 전달.
       failResult는 생략.
       7단계와 동일하게 worktree patches[]를 메인 트리에 적용.
     - missing → test-code-generator 호출: 해당 시나리오만 부분 재생성(5단계와 동일 프롬프트,
       scenarios를 missing 시나리오로 한정 — targetCallCheck 게이트 적용으로 재발 방지).
  2. 6단계 run-tests를 영향 클래스 한정으로 재실행. 실패하면 기존 7단계 보정 루프(#12) 재진입
     (적합성 교정이 green→red를 만드는 것은 정상 — 교정된 호출이 실제 결함을 드러낸 것).
  3. 10단계 verify-scenarios를 영향 시나리오 한정으로 재실행 → unmet 재계산.
  중단 조건: unmet == ∅ (성공) / 직전 라운드와 동일한 unmet 집합(무진전 — 즉시 중단) / 3라운드 소진.
```

- **하드 캡 3라운드 근거(#12의 명시적 예외)**: #12("진전 있는 한 무제한")는 실패 집합·커버리지 라인 같은 결정적 신호 전제다. 적합성 판정은 일부가 LLM 판단이라 verifier↔fixer 진동으로 unmet 집합이 계속 섞이며 "진전처럼 보일" 수 있어, 하드 캡 + 동일 집합 즉시 중단을 적용한다(#16).
- **수렴 후 회귀**: 루프 중 테스트가 수정·추가되었으면 8·9단계를 회귀 실행하고(기존 규약대로 `runResult` 재할당) 최종 10단계 확인을 1회 수행한다 — 여기서 새 unmet이 나오면 남은 라운드 예산 내에서만 처리(재순환 아님).
- **소진 후 잔여 unmet**: 대화형 = `AskUserQuestion`("수동 보정 계속 / partial로 종료"). CI = `status: "partial"` + 잔여 전량 보고.
- 라운드 로그를 `_workspace/10b_conformance_repair.json`에 저장:

```json
{
  "rounds": [
    {
      "round": 1,
      "unmetBefore": ["SC-013"],
      "routed": { "fixer": ["SC-013"], "regen": [] },
      "unmetAfter": [],
      "progress": true
    }
  ]
}
```

결과를 `conformanceRepairResult`로 저장하고, 최종 `conformanceResult`(마지막 10단계 재검증 결과)를 갱신한다.

---

### 최종 결과 집계 및 반환

모든 단계 결과(`coverageResult`, `mutationResult`, `conformanceResult` 포함)를 수렴해 `PipelineResult` JSON과 Markdown 보고서를 생성한다.

**집계 유효성 교차검증 (#21)**: `stages.measureCoverage`/`stages.mutationTest`는 무효 조건 검사(정의: fallback-policy #21)를 통과한 결과만 집계한다 — 게이트 미수행 산출물이면 집계하지 말고 해당 단계를 재실행한다.

**집계 매핑(중첩 필드 주의)**: `stages.measureCoverage`의 `line/branch/method/class`는 `coverageResult.coverage.*`(중첩)에서, `gatePassed`/`iterations`는 top-level에서 읽는다. `stages.verifyScenarios`의 `approved/satisfied/unsatisfied/missing`은 **최종**(10.5단계 이후 재검증된) `conformanceResult.totals.*`(중첩)에서 읽는다. `stages.conformanceRepair`는 `conformanceRepairResult`에서 읽는다(10.5단계 미진입 시 `"skipped"`). `stages.mutationTest`는 `mutationResult`의 top-level(`mutationScore`/`thresholdMet`/`iterations`)과 1:1.

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
    "refactorAdvisory": { "status": "ok", "flagged": 2, "included": 1, "excluded": 1, "mode": "interactive" },
    "generateScenarios": { "status": "ok", "scenarioCount": 8 },
    "scenarioApproval": { "status": "ok", "approved": 7, "excluded": 1, "mode": "interactive" },
    "generateTests": { "status": "ok", "fileCount": 3 },
    "runTests": { "status": "ok", "passed": 8, "failed": 0 },
    "repairTests": { "status": "skipped" },
    "measureCoverage": { "status": "ok", "line": 0.97, "branch": 0.92, "method": 0.98, "class": 1.00, "gatePassed": true, "iterations": 2 },
    "mutationTest": { "status": "ok", "mutationScore": 0.86, "thresholdMet": true, "iterations": 1 },
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
| 리팩토링 권고 | ok | 플래그 2 / 포함 1 / 제외 1 (대화형) → test_docs/refactoring/ 저장 |
| generate-scenarios | ok | 8개 시나리오 |
| 시나리오 승인 | ok | 승인 7 / 제외 1 (대화형) → test_docs/ 저장 |
| generate-tests | ok | 3개 파일 생성 |
| run-tests | ok | 8/8 통과 |
| repair-tests | 건너뜀 | — |
| measure-coverage | ok | 라인 0.97 / 브랜치 0.92 / 메서드 0.98 / 클래스 1.00 (2회 반복) |
| mutation-test | ok | mutation score 0.86 (목표 0.80 충족) |
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

---

## 실패 처리 및 중단 조건

| 상황 | 처리 방식 |
|---|---|
| **Phase E·E3b MCP 연결 검증 실패 (#20)** | 대화형·CI 양 모드 `status:"failed"` + remediation(플러그인 활성화 확인 → `node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs --ensure-only` → `/reload-plugins`/재시작). **파이프라인을 시작하지 않는다.** Grep/Read 대체 금지 |
| **파이프라인 도중 MCP 도구 호출 실패 또는 `JAVAPARSER_REQUIRED`/`degraded:true` 수신 (#20/#2)** | 즉시 중단(`status:"failed"` + remediation). **Grep/Read/직접 파싱으로 대체 생성 금지** — MCP 도구는 필수 경로다 |
| 1·2단계(병렬) 모두 `failed` | 3단계 이후 중단, `status: "failed"` 반환 |
| 1단계만 `failed` | specResult 없이 진행, `status: "partial"` |
| 2단계만 `failed` | `status: "failed"` 반환 (AST 없이 이후 단계 불가) |
| 3단계 `failed` | `status: "failed"` 반환 |
| 3.5단계 권고 게이트 (#19) | 대화형=`AskUserQuestion`(전체 포함/일부 제외/전체 제외). 권고 `.md`는 항상 작성. CI=전 대상 포함+경고 후 진행 |
| 3.5단계 전체 제외 | 포함 대상이 0건이면 `status: "partial"` + "생성 대상 없음(전량 리팩토링 권고)" 보고 후 중단 |
| 3.5단계 에이전트 `failed` | 판정 불가 시 **경고 후 전 대상 포함으로 진행**(`warnings`에 REFACTOR_ADVISORY_FAILED — 권고는 보조 게이트, 파이프라인 차단 안 함) |
| 4단계 `partial` | 가능한 시나리오로 진행 |
| 4.5단계 승인 게이트 (#15) | 대화형=`AskUserQuestion`(전체 승인/일부 제외·수정/재설계). 승인분만 5단계로. CI=자동 승인+기록 후 진행 |
| 4.5단계 전체 제외 | 승인된 시나리오가 0건이면 `status: "partial"` + "승인된 시나리오 없음" 보고 후 중단 |
| 5단계 `files` 비어 있음 | `status: "failed"` 반환 |
| 5단계 target 호출 게이트 | `targetCallCheck` 누락 또는 `"mismatch"` 파일은 Write 금지 + `warnings`(`SCENARIO_TARGET_MISMATCH`) 보고. 전 파일 mismatch면 `status: "failed"` |
| 6단계 `BUILD_TOOL_UNDETECTED` (#5) | 대화형=`AskUserQuestion("gradle/maven?")` 후 진행 / CI=`status:"failed"` |
| 0.6단계 빌드 능력 미비 (#17) | JaCoCo XML/PITest 미적용 → 대화형=승인 후 스니펫 주입(`buildChanges[]`)·재감지 / 거부 시 8·9단계 `skipped` / CI=자동 주입 금지·remediation 중단 |
| 0.6단계 콜드 캐시 (#18) | `primed:false` → 대화형=승인 후 6단계 1회 `online=True` 프라이밍 / CI=`BUILD_TEST_ALLOW_NETWORK=1` 옵트인·워밍업 안내 |
| 7단계 보정 루프 (#12) | **그린 될 때까지 재시도**(진전 있는 한 계속). 동일 실패 시그니처 **3회 연속(무진전)**이면 `partial`로 잔여 전량 보고 후 종료 |
| 8단계 커버리지 게이트 (#12/#21) | 게이트 충족까지 재측정/보정. 동일 미커버 집합 **3회 연속(무진전)**이면 `partial` + `remainingGaps[]` 전량 보고(임의 제외 금지). 무효 산출물·advisory 비면제는 #21을 따름(8단계 재실행, 훅이 기록 차단) |
| 9단계 뮤테이션 (#12/#21) | score 도달까지 강화. 동일 survivor 집합 **3회 연속(무진전)**이면 `partial` + `survivingMutants[]` + 동등 mutant 사유 보고. 무효 산출물·advisory 비면제는 #21을 따름(9단계 재실행, 훅이 기록 차단) |
| 10단계 적합성 (#16) | `unmet` 존재 시 **10.5단계 자동 보정 루프**(unsatisfied→test-fixer 모드 B / missing→부분 재생성, 최대 3라운드·동일 unmet 집합 즉시 무진전 중단, 대화형·CI 동일 자동 수행) → 소진 후 잔여: 대화형=`AskUserQuestion`(수동 보정 계속/partial 종료), CI=`status: "partial"` + 잔여 전량 보고. 임의 제외 금지 |
| junitPolicy `strict-5x` | `warnings`에 버전 충돌 경고 추가 후 진행 |

MCP 필수 경로: 모든 단계에서 MCP 도구(repo-ast·spec-doc·build-test)는 **필수 경로**다 — 미가용·호출 실패·`degraded:true`/`JAVAPARSER_REQUIRED` 응답 시 대체하지 말고 중단한다(fallback-policy.md #20/#2, Grep/Read/직접 파싱 대체 금지).

보안: 각 단계 subagent의 권한 모델은 **해당 에이전트 자신의 frontmatter `tools:` 목록**(`agents/*.md`)으로 정의된다(필요 시 `disallowedTools`로 추가 제한). 쉘 인자 escaping, 네트워크 기본 차단, redaction 필수.
성능: 1·2단계 병렬. 이후 단계는 순차. 대형 저장소는 targets로 스코프를 좁혀 AST 파싱 비용 절감. context 절약을 위해 각 단계 결과는 JSON summary만 메인에 환원.
