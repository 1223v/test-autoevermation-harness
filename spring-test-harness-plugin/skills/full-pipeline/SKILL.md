---
name: full-pipeline
description: Spring 프로젝트에 대해 인터랙티브 설정·스펙 인제스트·AST 분석·소스 분석·시나리오 설계·테스트 생성·실행·보정·커버리지 게이트(near-100%)·뮤테이션 강화까지 end-to-end 파이프라인을 오케스트레이션한다. "스프링 테스트 생성", "하네스 실행", "테스트 파이프라인", "전체 테스트 자동화", "커버리지 100%"처럼 테스트 생성이 필요할 때, 그리고 후속 작업 — "테스트 다시 생성", "재실행", "커버리지 더 올려", "이 패키지만 다시", "결과 개선", "보완", "업데이트", "뮤테이션만 다시" — 처럼 이전 실행을 이어가거나 부분 재실행하는 요청에도 반드시 이 스킬을 사용한다.
---

> **흐름도**: 전체 구동 흐름을 Mermaid로 시각화한 문서는 [docs/pipeline-flow.md](../../docs/pipeline-flow.md) 참조.

## 목적

`HarnessRequest` JSON을 입력받아, 먼저 `configure-harness`로 인터랙티브 설정(`HarnessConfig`)을 받은 뒤, 스킬들(configure-harness, ingest-specs, analyze-ast, analyze-source, generate-scenarios, generate-tests, run-tests, repair-tests, measure-coverage, mutation-test, verify-scenarios)을 정해진 순서와 병렬 전략에 따라 오케스트레이션한다. 각 단계의 결과를 수렴해 다음 단계로 전달하고, **near-100% 커버리지 게이트와 뮤테이션 강화 루프**를 수렴시킨 후 **마지막에 시나리오 적합성 검증**까지 마치고 최종 Markdown 보고서와 상태 JSON을 반환한다.

**시나리오 승인 + 산출물(`test_docs/`).** 시나리오 설계(4단계) 직후, 테스트 생성(5단계) **전에 사용자 승인 게이트**를 둔다 — 시나리오를 대상 프로젝트의 `test_docs/scenarios/<id>.md`로 저장하고, 대화형은 `AskUserQuestion`으로 승인/제외·수정/재설계를 묻는다(승인분만 생성으로 진행). 비대화형·CI는 자동 승인 후 기록. 모든 단계가 끝나면 **마지막 단계(10단계)에서 시나리오 적합성을 검증**해(통과한 테스트가 시나리오 given/when/then을 실제로 만족하는지) `test_docs/`를 **시나리오 ↔ 테스트코드 ↔ 결과**로 정리한다. 정본: [references/scenario-docs.md](../../references/scenario-docs.md).

**가장 먼저 Phase E 환경 세팅을 끝낸다.** 0단계 이전에 [references/environment-setup.md](../../references/environment-setup.md)(SSOT) 체크리스트를 TODO로 만들어 환경(역량·빌드도구·프로파일·실행 JDK)을 **선제적으로 전부 세팅**한다 — fallback을 파이프라인 도중에 마주치기 전에 제거한다. 여기에 **대상 빌드 능력(JaCoCo XML·PITest 플러그인)과 의존성 캐시 프라이밍**(0.6단계, E11·E12)이 포함된다 — 미비 시 커버리지/뮤테이션(8·9단계)·첫 실행(6단계)이 깨지므로 `detect→approve→inject`로 선제 처리한다([references/build-provisioning.md](../../references/build-provisioning.md)). 자동으로 고칠 수 있는 항목은 **대화형=항목별 `AskUserQuestion` 후 함께 세팅 / 비대화형·CI=자동 세팅**(`pip install`·`mvn package`). 미충족 잔여 항목이 있으면 파이프라인을 **시작하지 않는다**. 런타임 의사결정 fallback은 [references/fallback-policy.md](../../references/fallback-policy.md)(SSOT)를 따른다 — **대화형은 `AskUserQuestion`, 비대화형은 결정적 항목 자동 세팅·그 외 하드 중단**(remediation 안내).

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

### Phase E: 환경 세팅 (0단계 이전 — 선행 필수)

전처리 직후, 0단계 진입 **전에** [references/environment-setup.md](../../references/environment-setup.md) 체크리스트를 **TodoWrite로 만들어 전부 통과**시킨다. 이 단계는 `configure-harness`의 Preflight(Phase E)와 동일 절차이며, `configure-harness`를 호출하면 그 안에서 수행된다(중복 실행 금지 — 이미 통과한 `_workspace/00_config-harness.json`이 있으면 재사용).

- **대상 항목**: E1 Python 3.10+ · E2 MCP SDK · E3 MCP 서버 등록 · E4 JDK 17+ · E5 Maven · E6 JavaParser jar · E7 JDT LS+Java21(**선택**) · E10 테스트 실행 JDK 호환. (E8 빌드도구·E9 Spring 프로파일은 0단계 configure-harness 0.5단계에서, **E11 빌드 능력(JaCoCo XML·PITest)·E12 의존성 캐시 프라이밍은 0.6단계**에서 확정 — 6단계 run-tests 이전 필수. 정본: [references/build-provisioning.md](../../references/build-provisioning.md).)
- **세팅 방식**: 자동 가능 항목(E2·E6)은 **대화형=항목별 `AskUserQuestion` 후 함께 세팅 / CI=자동 실행**(`pip install -r mcp/requirements.txt`, `cd mcp/javaparser-cli && mvn -q -DskipTests package`). assist 항목(E1·E4·E5·E10)은 대화형=설치/런타임 안내 질문, CI=미충족 시 하드 중단. E7(JDT LS)은 **선택** — 미가용이면 AST-only degrade로 진행(중단 안 함).
- **검증 후 체크**: 각 세팅 뒤 재감지로 통과 확인 후 `completed` 표시.
- **게이트**: E1–E6 + E10이 모두 통과하지 못하면 0단계로 진행하지 않고 `status:"failed"` + remediation으로 중단한다(E7 JDT LS는 **선택** — 미가용 시 AST-only degrade, 차단하지 않음).

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
  "springProfile": <springProfile (0단계 configure-harness 산출 — 인터뷰로 확정된 프로파일을 그대로 전달)>
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

> **콜드 캐시 프라이밍(#18)**: 0.6단계 `check_dependency_cache`가 `primed:false`였고 사용자가 승인했다면, **첫 run-tests만** `run_targeted_tests(online=True)`로 1회 온라인 실행(또는 Maven `dependency:go-offline` 선행)하고 이후 호출은 오프라인 유지한다. 0.6단계에서 JaCoCo XML/PITest 플러그인을 새로 주입(#17)한 경우에도 1회 프라이밍이 필요하다. 근거: Gradle `--offline`은 미캐시 모듈 시 빌드 실패([build-provisioning.md](../../references/build-provisioning.md) §2).

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

보정 완료 후 `run-tests`를 `rerunTargets`로 재실행. **그린이 될 때까지 재시도**한다(fallback-policy.md #12). `retryCount`/`maxRepairRetries`는 **진전 추적 단위**일 뿐 상한이 아니다 — 실패가 줄어드는 한 계속하고, **직전과 동일한 실패가 3회 연속(무진전)**이면 `partial`로 잔여 실패를 전량 보고하고 중단한다.

---

### 8단계: measure-coverage (near-100% 게이트 루프)

테스트가 통과 상태(6/7단계 완료)가 되면 `measure-coverage` 스킬로 JaCoCo 게이트 루프를 돌린다.

```
/spring-test-harness:measure-coverage
```

- build-test-mcp로 JaCoCo 리포트 생성 → `parse_jacoco_report` → `coverage_gate(line,branch,method,class)`.
- 미달 시 `coverage-closer` 에이전트가 `uncovered[]`를 받아 추가 테스트 생성 → 게이트 충족까지 재측정(fallback-policy.md #12: 진전 있는 한 계속, 동일 미커버 집합 3회 연속이면 무진전으로 보고 후 중단).
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

### 10단계: verify-scenarios (시나리오 적합성 검증 — 마지막)

모든 단계(생성·실행·커버리지·뮤테이션)가 끝나면 `verify-scenarios` 스킬로 **승인된 각 시나리오가 실제로 충족되었는지** 검증한다. 단순 통과 여부가 아니라, 통과한 테스트가 시나리오의 given/when/then을 만족하는지 확인하고 `test_docs/`를 시나리오↔테스트코드↔결과로 정리한다. 정본: [references/scenario-docs.md](../../references/scenario-docs.md) §4.

```
/spring-test-harness:verify-scenarios
```

```
Task(
  subagent_type="scenario-conformance-verifier",
  model="inherit",
  prompt="""
입력:
{
  "approvedScenarios": <approvedScenarios>,
  "generatedFiles": <genResult.files[].path>,
  "runResult": <runResult (최종, 보정 후)>,
  "coverageResult": <coverageResult>,
  "projectRoot": <projectRoot>,
  "testDocsDir": "test_docs"
}

지시:
- scenarioRef(메서드명 sc001_… + javadoc scenarioRef/criteriaRef)로 시나리오 → 테스트 메서드를 매핑하라.
- satisfied(매핑+통과+then 단언 충족) / unsatisfied(매핑되나 실패·단언 부족) / missing(매핑 없음)으로 판정하라.
- // then 단언이 시나리오 then을 빠짐없이 반영하는지 테스트 본문과 대조해 판정하라(thenCovered 충족/전체).
- test_docs/scenarios/<id>.md의 "테스트 코드 매핑"·"검증 결과" 섹션과 INDEX.md를 갱신하라(references/scenario-docs.md §2).
- 테스트 코드를 새로 생성/수정하지 마라(검증·문서화 전용). 소스 원문·민감정보 기록 금지.
- ConformanceResult JSON으로 반환하라.
"""
)
```

결과를 `conformanceResult`로 저장하고 `_workspace/10_conformance.json`에 보존한다.

**게이트 (fallback-policy.md #16)**: `unmet`(unsatisfied/missing)이 하나라도 있으면 파이프라인 `status: "partial"`로 잔여를 전량 보고한다. 전부 satisfied라야 `ok`. 대화형은 잔여에 대해 `AskUserQuestion`("추가 보정 시도 / partial로 종료")로 5→6→(8·9) 부분 재실행을 선택할 수 있다. CI는 `partial`로 종료. 임의 제외·무시 금지.

---

### 최종 결과 집계 및 반환

모든 단계 결과(`coverageResult`, `mutationResult`, `conformanceResult` 포함)를 수렴해 `PipelineResult` JSON과 Markdown 보고서를 생성한다.

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
    "scenarioApproval": { "status": "ok", "approved": 7, "excluded": 1, "mode": "interactive" },
    "generateTests": { "status": "ok", "fileCount": 3 },
    "runTests": { "status": "ok", "passed": 8, "failed": 0 },
    "repairTests": { "status": "skipped" },
    "measureCoverage": { "status": "ok", "line": 0.97, "branch": 0.92, "method": 0.98, "class": 1.00, "gatePassed": true, "iterations": 2 },
    "mutationTest": { "status": "ok", "mutationScore": 0.86, "thresholdMet": true, "iterations": 1 },
    "verifyScenarios": { "status": "ok", "approved": 7, "satisfied": 7, "unsatisfied": 0, "missing": 0 }
  },
  "generatedFiles": [
    "src/test/java/com/example/order/OrderServiceTest.java",
    "src/test/java/com/example/order/OrderControllerTest.java"
  ],
  "scenarioDocs": [
    "test_docs/INDEX.md",
    "test_docs/scenarios/SC-001.md"
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
| 시나리오 승인 | ok | 승인 7 / 제외 1 (대화형) → test_docs/ 저장 |
| generate-tests | ok | 3개 파일 생성 |
| run-tests | ok | 8/8 통과 |
| repair-tests | 건너뜀 | — |
| measure-coverage | ok | 라인 0.97 / 브랜치 0.92 / 메서드 0.98 / 클래스 1.00 (2회 반복) |
| mutation-test | ok | mutation score 0.86 (목표 0.80 충족) |
| verify-scenarios | ok | 승인 7건 satisfied 7 / unsatisfied 0 / missing 0 |

## 시나리오 적합성 (test_docs/)
- 산출물: `test_docs/INDEX.md` (시나리오↔테스트코드↔결과 매핑)
- 승인 7건 모두 satisfied (given/when/then 충족)

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
| 4.5단계 승인 게이트 (#15) | 대화형=`AskUserQuestion`(전체 승인/일부 제외·수정/재설계). 승인분만 5단계로. CI=자동 승인+기록 후 진행 |
| 4.5단계 전체 제외 | 승인된 시나리오가 0건이면 `status: "partial"` + "승인된 시나리오 없음" 보고 후 중단 |
| 5단계 `files` 비어 있음 | `status: "failed"` 반환 |
| 6단계 `BUILD_TOOL_UNDETECTED` (#5) | 대화형=`AskUserQuestion("gradle/maven?")` 후 진행 / CI=`status:"failed"` |
| 0.6단계 빌드 능력 미비 (#17) | JaCoCo XML/PITest 미적용 → 대화형=승인 후 스니펫 주입(`buildChanges[]`)·재감지 / 거부 시 8·9단계 `skipped` / CI=자동 주입 금지·remediation 중단 |
| 0.6단계 콜드 캐시 (#18) | `primed:false` → 대화형=승인 후 6단계 1회 `online=True` 프라이밍 / CI=`BUILD_TEST_ALLOW_NETWORK=1` 옵트인·워밍업 안내 |
| 7단계 보정 루프 (#12) | **그린 될 때까지 재시도**(진전 있는 한 계속). 동일 실패 시그니처 **3회 연속(무진전)**이면 `partial`로 잔여 전량 보고 후 종료 |
| 8단계 커버리지 게이트 (#12) | 게이트 충족까지 재측정/보정. 동일 미커버 집합 **3회 연속(무진전)**이면 `partial` + `remainingGaps[]` 전량 보고(임의 제외 금지) |
| 9단계 뮤테이션 (#12) | score 도달까지 강화. 동일 survivor 집합 **3회 연속(무진전)**이면 `partial` + `survivingMutants[]` + 동등 mutant 사유 보고 |
| 10단계 적합성 (#16) | `unmet`(unsatisfied/missing) 존재 시 `status: "partial"` + 잔여 전량 보고. 대화형=`AskUserQuestion`(추가 보정/partial 종료), CI=partial 종료. 임의 제외 금지 |
| junitPolicy `strict-5x` | `warnings`에 버전 충돌 경고 추가 후 진행 |

보안: 각 단계 subagent는 REPORT.md 권한 모델에 따라 tools/disallowedTools가 제한됨. 쉘 인자 escaping, 네트워크 기본 차단, redaction 필수.
성능: 1·2단계 병렬. 이후 단계는 순차. 대형 저장소는 targets로 스코프를 좁혀 AST 파싱 비용 절감. context 절약을 위해 각 단계 결과는 JSON summary만 메인에 환원.
