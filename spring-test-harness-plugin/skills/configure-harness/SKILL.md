---
name: configure-harness
description: Spring 테스트 하네스 실행 전 환경 세팅(Phase E)과 인터랙티브 인터뷰를 수행하고 HarnessConfig JSON을 생성한다. "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "뮤테이션 설정", "하네스 구성"처럼 설정 또는 초기화가 필요한 상황에서 자동 호출된다. CI(claude -p)에서는 인터뷰를 건너뛰되 환경 세팅의 결정적 항목은 자동 수행하고, 미충족 필수 항목은 HarnessRequest 값으로 채우거나 중단한다.
---

## 목적

먼저 대상의 **Spring Boot 버전 프로파일(Boot 2.0–4.x)을 감지/확정**(0.5단계, RESEARCH_NOTES §8)한 뒤, 사용자와 4항목 인터뷰(RESEARCH_NOTES §7)를 진행하여 `HarnessConfig` JSON을 생성한다. 생성된 `HarnessConfig`(`springProfile` 포함)는 `full-pipeline` 및 개별 스킬(measure-coverage, mutation-test 등)의 입력으로 사용된다.

**환경 세팅 선행(필수)**: 이 스킬은 0단계 인터뷰 전에 **Phase E 환경 세팅 체크리스트**([references/environment-setup.md](../../references/environment-setup.md), SSOT)를 TODO 리스트로 **먼저 통과**시킨다 — fallback을 파이프라인 도중에 마주치기 전에 선제적으로 제거한다. 자동으로 고칠 수 있는 항목은 **대화형=항목별 `AskUserQuestion` 후 함께 세팅 / 비대화형·CI=자동 세팅**한다.

**Fallback 정책 준수(필수)**: 런타임 의사결정은 [references/fallback-policy.md](../../references/fallback-policy.md)(SSOT)를 따른다. 미충족 조건(역량 미설치, 버전 미감지, 미지정 입력, 프로파일 충돌)은 **침묵 fallback·임의 기본값 없이** 처리한다 — **대화형은 `AskUserQuestion`으로 질문/함께 세팅**, **비대화형/CI는 결정적 항목 자동 세팅·그 외 하드 중단(remediation 안내)**.

**인터랙티브 CLI 전용 주의**: `AskUserQuestion`은 대화형 Claude Code CLI에서만 의미가 있다. `claude -p`/CI에서는 질문할 수 없으므로, **미충족 필수 조건이 있으면 `status:"failed"` + remediation으로 중단**한다(과거의 "인터뷰 스킵 + 기본값" 동작은 정책 변경으로 제거됨). 사용자는 `HarnessRequest`에 값을 미리 채워 중단을 피한다.

---

## 자동 호출 조건

- 사용자가 "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "뮤테이션 설정", "하네스 구성", "설정 인터뷰"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 0단계(전처리 이전)에서 `HarnessConfig`가 없을 때 선행 호출될 때
- 사용자가 `/spring-test-harness:configure-harness`를 직접 실행할 때

## 수동 호출 예시

```
/spring-test-harness:configure-harness
```

또는 기존 HarnessRequest를 기반으로 일부 항목만 재설정:

```json
{
  "projectRoot": "/path/to/spring-project",
  "skipInterview": false
}
```

---

## 인터랙티브 모드 감지

다음 조건 중 하나라도 해당하면 **CI 모드**(인터뷰 스킵)로 동작한다:

- `skipInterview: true`가 명시된 경우
- 환경 변수 `CI=true` 또는 `CLAUDE_NO_PROMPT=true`가 설정된 경우
- `claude -p` 플래그로 호출된 비대화형 세션인 경우
- `HarnessRequest` 입력에 4개 인터뷰 항목이 모두 채워진 경우

CI 모드에서는 아래 단계별 절차 중 인터뷰 단계를 건너뛰고 바로 "HarnessConfig 생성" 단계로 이동한다.

---

## 단계별 절차

### Preflight 단계 (Phase E): 환경 세팅 체크리스트 — *선(先) 세팅, 후(後) 실행*

설정 시작 전에 하네스가 원활히 돌기 위한 **환경을 먼저 다 세팅**한다. 정본 절차·명령·근거는
[references/environment-setup.md](../../references/environment-setup.md)(SSOT). fallback을 파이프라인 도중에 "마주치기" 전에 여기서 **선제적으로 제거**한다.

**TODO 리스트로 진행한다.** 시작 시 `TodoWrite`로 아래 항목을 만들고 `pending → in_progress → completed`로 하나씩 체크한다(진척 가시화).

| TODO | 항목 | 감지 | 미충족 시 세팅 |
|---|---|---|---|
| E1 | Python 3.10+ | `python3 -c "import sys;assert sys.version_info>=(3,10)"` | 설치 경로 안내(assist) |
| E2 | MCP SDK `mcp[cli]>=1.2.0` | `python3 -c "import mcp"` | `python3 -m pip install -r mcp/requirements.txt` (auto) |
| E3 | MCP 서버 3종 등록 | `.mcp.json` + 서버 모듈 로드 | import 실패는 E2로 귀결 |
| E4 | JDK 17+ | `java -version`≥17 | 설치/`JAVA_HOME` 안내(assist) |
| E5 | Maven 3.6.3+ | `mvn -version` | jar 이미 있으면 생략 |
| E6 | JavaParser CLI jar | `REPO_AST_JAVAPARSER_JAR` 또는 `mcp/javaparser-cli/target/*-shaded.jar` | `(cd mcp/javaparser-cli && mvn -q -DskipTests package)` (auto) |
| E7 | JDT LS + Java 21+ (선택) | `jdtls` PATH + `.lsp.json` + Java 21+ | 미가용이면 AST-only degrade(중단 안 함, optional). **감지 결과를 `HarnessConfig.lspAvailable`에 반영**(가용=`true`, 미가용=`false`) |
| E10 | 테스트 실행 JDK ↔ Mockito 호환 | 실행 JDK major vs Mockito/ByteBuddy 지원 범위 | 17/21 LTS 권장 또는 Mockito 5.16+/experimental 플래그 |

> E8(빌드도구)·E9(Spring 프로파일)는 데이터 감지라 아래 **0.5단계**에서 함께 확정한다.

**세팅 방식 (정책: environment-setup.md)**
- **대화형 — 항목별로 함께 세팅**: 자동으로 고칠 수 있는 항목(E2·E6 등)은 항목마다 `AskUserQuestion("〈항목〉이 없습니다. 지금 함께 세팅할까요?")` → "예"면 그 자리에서 설치/빌드 실행 → **재감지 검증** → `completed`. "아니오"면 `status:"failed"` 중단. assist 항목(E1·E4·E5)은 설치/경로 안내 질문, 사용자가 못 갖추면 중단. E7(JDT LS)은 **선택** — 미가용이면 안내만 하고 AST-only degrade로 진행(중단 안 함).
- **비대화형/CI — 항상 자동 세팅**: 결정적 항목(E2·E6)은 질문 없이 `pip install`/`mvn package`를 **자동 실행** 후 재검증. 자동 세팅이 실패하거나 시스템 항목(E1·E4·E5·E7)이 없으면 `status:"failed"` + remediation으로 중단(`HarnessRequest`로 사전 충족 가능).
- **검증 후 체크**: 세팅 액션 뒤 반드시 재감지해서 통과를 확인한 뒤에만 `completed`로 표시한다.

필수 항목 **E1·E2·E3(런타임) + E10(실행 JDK 호환)**(그리고 0.5단계에서 확정되는 **E8·E9 빌드도구·프로파일**)이 `completed`여야 0단계로 진행한다. **E4·E5·E6(JavaParser jar용 JDK/Maven/빌드)와 E7(JDT LS)은 선택** — 미가용 시 각각 정규식·AST-only degrade로 진행(차단하지 않음). 정본: [environment-setup.md](../../references/environment-setup.md) 「통과 기준」. (예시: E2 `AskUserQuestion(options=["예 — python3 -m pip install -r mcp/requirements.txt 실행","아니오 — 중단"])`, E6 `options=["예 — javaparser jar 빌드","아니오 — 정규식 degrade로 진행"]`.)

> **`lspAvailable`은 E7 감지 결과로 설정한다** — `jdtls`(PATH) + `.lsp.json`(plugin.json `lspServers`로 등록됨) + Java 21+ 런타임이 모두 가용이면 `true`, 아니면 `false`. 아래 `HarnessConfig` 출력 예시는 미가용 기본값(`false`)이다. `lspAvailable:true`일 때만 `analyze-source`/`full-pipeline`의 LSP 보강(정의이동·참조탐색) 경로가 활성화된다.

### 0단계: 모드 판별

CI 모드 여부를 확인한다. CI 모드이면 인터뷰 단계(1~4)는 건너뛰되, **0.5단계(Spring 프로파일 감지)는 항상 수행**한다.

---

### 0.5단계: Spring 버전 프로파일 감지 (항상 수행 — Boot 2.0–4.x 하위호환)

테스트 관용구(네임스페이스·JUnit 엔진·Mock 애노테이션·Java 베이스라인)는 대상의 Spring Boot 버전에 따라 달라지므로, **인터뷰 전에 먼저 프로파일을 확정**한다. 근거·매트릭스: `[[../../RESEARCH_NOTES.md]]` §8, [references/version-compatibility.md](../../references/version-compatibility.md).

```
build-test-mcp.detect_spring_profile(root=projectRoot)
→ { springProfile{...degraded}, interviewRequired, requiresConfirmation, conflicts[], notes, nextActions }
```

- **감지 성공(`degraded:false`, `requiresConfirmation:false`)**: `springProfile`을 그대로 `HarnessConfig`에 채택. `notes`는 `warnings`에 전달.

- **버전 미감지(`interviewRequired:true`) (#4)**: **프로파일을 가정하지 않는다.**
  - 대화형: 아래로 질문하고, 사용자가 선택하지 않으면 **중단**.

```
AskUserQuestion(
  question="대상 프로젝트의 Spring Boot 메이저 버전을 선택하세요. (빌드 파일에서 자동 감지하지 못했습니다)",
  options=["2.x (javax, Java 8)", "3.x (jakarta, Java 17)", "4.x (jakarta, 최신)"]
)
```

  2.x 선택 시 JUnit 엔진을 후속 질문으로 확정(2.0–2.1 기본 JUnit4):

```
AskUserQuestion(
  question="이 프로젝트의 테스트는 어떤 JUnit을 사용하나요?",
  options=["JUnit 5 (Jupiter, @Test/@DisplayName)", "JUnit 4 (@RunWith(SpringRunner.class)/org.junit.Test)"]
)
```

  선택 결과로 `springProfile` 구성(2.x→`javax/MockBean/Java8`; 3.0–3.3→`MockBean`; 3.4+/4.x→`MockitoBean/jakarta/Java17`; import·게이트는 version-compatibility.md).
  - **CI**: 가정 금지. `status:"failed"`, `errors`에 `INTERVIEW_REQUIRED` + "HarnessRequest.springVersion을 명시하세요". 중단.

- **프로파일 충돌(`requiresConfirmation:true`) (#6)**: 빌드파일 값과 소스/기존테스트 값이 다르다(`conflicts[]`). **자동 적용 금지.**
  - 대화형: 각 충돌(namespace/junitEngine)에 대해 어느 쪽을 따를지 질문 후 확정.

```
AskUserQuestion(
  question="감지 충돌: namespace가 빌드파일=<buildFileValue> vs 소스=<sourceValue> 입니다. 어느 것을 사용할까요?",
  options=["빌드파일 값(<buildFileValue>)", "소스 값(<sourceValue>)"]
)
```

  - CI: `status:"failed"`, `errors`에 `PROFILE_CONFLICT` + 충돌 내용. 중단.

확정된 `springProfile`은 5단계 `HarnessConfig`에 포함되어 generate-scenarios/generate-tests/measure-coverage 전 단계로 전파된다.

---

### 0.6단계: 빌드 능력 프로비저닝 + 캐시 프라이밍 (항상 수행 — 6/8/9단계 선행)

대상 빌드 파일이 **JaCoCo XML·PITest**를 낼 수 있는지, 의존성 캐시가 **첫 오프라인 실행**을 견디는지 확정한다.
JaCoCo 에이전트는 `test` 실행 중 attach되므로 이 단계는 반드시 **6단계 run-tests 이전**에 끝낸다. 정본: [references/build-provisioning.md](../../references/build-provisioning.md), 정책: fallback-policy.md #17·#18.

**(a) 빌드 능력(E11, #17)** — `detect → approve → inject`
```
build-test-mcp.detect_build_capabilities(root=projectRoot, junit_engine=springProfile.junitEngine)
→ { capabilities{jacoco,jacocoXml,pitest,pitestJunit5}, missing[], proposedChanges[], remediation }
```
- **충족(`missing:[]`)**: 그대로 진행.
- **누락(대화형)**: `missing`/`proposedChanges`를 표로 보여주고 질문 →
```
AskUserQuestion(
  question="대상 빌드 파일에 커버리지/뮤테이션 설정을 자동 주입할까요? (JaCoCo XML 활성화·PITest 플러그인)",
  options=["예 — 최소 스니펫 주입", "아니오 — 해당 단계 건너뜀(skipped 보고)"]
)
```
  "예"면 `proposedChanges[]`의 스니펫을 빌드 파일에 **최소 주입**(Edit)하고 `buildChanges[]`에 기록 → `detect_build_capabilities` **재감지**로 통과 확인. "아니오"면 8/9단계를 `skipped`(사유: 사용자 거부)로 표시.
- **누락(CI)**: 자동 주입 **금지**. `status:"failed"` + `errors`에 `missing` 코드와 스니펫을 remediation으로 명시하고 중단(사용자는 빌드 파일에 미리 반영하거나 `HarnessRequest`로 회피).

**(b) 캐시 프라이밍(E12, #18)**
```
build-test-mcp.check_dependency_cache(build_tool=buildTool, root=projectRoot) → { primed, primeCommand, recommendation }
```
- **대화형**: `primed:false`이거나 방금 (a)에서 플러그인을 주입했다면 →
```
AskUserQuestion(
  question="의존성/플러그인을 1회 온라인으로 받아올까요? (이후 실행은 오프라인 유지)",
  options=["예 — 1회 온라인 프라이밍", "아니오 — 오프라인 진행(실패 위험)"]
)
```
  "예"면 6단계 첫 실행을 `run_targeted_tests(online=True)`로 1회 수행(또는 Maven `mvn dependency:go-offline`), 이후는 오프라인. "아니오"면 오프라인 그대로(실패 시 #18대로 보고).
- **CI**: 자동 온라인 전환 금지 — `BUILD_TEST_ALLOW_NETWORK=1` 옵트인 또는 사전 캐시 워밍업을 안내. 미충족이면 첫 실행 실패를 `partial`로 보고.

감지·주입·프라이밍 결과는 `_workspace/00b_build_provision.json`에 보존한다(부분 재실행 시 재사용, 중복 주입 금지).

---

### 1단계: 인터뷰 항목 (a) — 스펙 문서 경로

```
AskUserQuestion(
  question="테스트 생성에 참고할 스펙 문서 경로가 있으면 입력하세요 (없으면 Enter로 건너뜁니다).\n예: docs/api-spec.md, requirements/order-spec.pdf",
  options=["경로 직접 입력", "건너뜀 (스펙 없이 진행)"]
)
```

- 입력값을 `specDocPaths[]`에 추가한다.
- 여러 경로를 쉼표로 구분해 입력할 수 있다.
- 건너뜀 선택 시 `specDocPaths: []`로 설정하고 `warnings`에 "스펙 문서 미지정 — ingest-specs가 partial로 실행됩니다" 추가.

---

### 2단계: 인터뷰 항목 (b) — 테스트 생성 대상

```
AskUserQuestion(
  question="테스트를 생성할 대상을 지정하세요. 패키지, 클래스 FQCN, 또는 모듈명을 입력할 수 있습니다 (없으면 자동 탐지).\n예: com.example.order, com.example.payment.PaymentService",
  options=["직접 입력", "자동 탐지 (전체 Spring 컴포넌트 스캔)"]
)
```

- 입력값을 `targets[]`에 추가한다.
- 자동 탐지 선택 시 `targets: []`로 설정 — analyze-ast 단계에서 `list_spring_components`로 자동 탐색.
- 멀티 모듈 프로젝트의 경우 모듈명을 입력받아 `targetModules[]`에 추가.

```
AskUserQuestion(
  question="멀티 모듈 프로젝트라면 대상 모듈명을 입력하세요 (단일 모듈이면 건너뜁니다).\n예: order-service, payment-service",
  options=["모듈명 입력", "단일 모듈 / 건너뜀"]
)
```

---

### 3단계: 인터뷰 항목 (c) — 뮤테이션 테스트 깊이/대상

```
AskUserQuestion(
  question="PITest 뮤테이션 테스트 설정을 선택하세요.",
  options=[
    "기본 (mutators=DEFAULTS, threshold=0.80)",
    "강화 (mutators=STRONGER, threshold=0.80)",
    "직접 지정"
  ]
)
```

"직접 지정" 선택 시 추가 질문:

```
AskUserQuestion(
  question="뮤테이터 세트를 선택하세요.",
  options=["DEFAULTS", "STRONGER", "ALL"]
)
```

```
AskUserQuestion(
  question="뮤테이션 score 목표(0.0–1.0)를 입력하세요. 기본값: 0.80",
  options=["0.80 (기본)", "0.85", "0.90", "직접 입력"]
)
```

```
AskUserQuestion(
  question="PITest targetClasses 패턴을 지정하세요 (없으면 targets와 동일하게 적용).\n예: com.example.order.*",
  options=["targets와 동일", "직접 입력"]
)
```

결과를 `mutation` 블록에 저장(최종 `HarnessConfig.mutation`으로 병합):
```json
{
  "mutators": "DEFAULTS",
  "targetClasses": [],
  "mutationThreshold": 0.80
}
```

---

### 4단계: 인터뷰 항목 (d) — 커버리지 임계값 + 제외 규칙

```
AskUserQuestion(
  question="커버리지 게이트 임계값을 설정하세요.",
  options=[
    "기본값 사용 (LINE=0.95, BRANCH=0.90, METHOD=0.95, CLASS=1.00)",
    "직접 지정"
  ]
)
```

"직접 지정" 선택 시 각 카운터별 추가 질문:

```
AskUserQuestion(
  question="LINE 커버리지 목표를 입력하세요 (기본: 0.95)",
  options=["0.95", "0.90", "0.85", "직접 입력"]
)
```

(BRANCH, METHOD, CLASS도 동일 패턴으로 질문)

```
AskUserQuestion(
  question="커버리지 게이트에서 제외할 패턴을 선택하거나 추가하세요.",
  options=[
    "기본 제외 패턴 사용 (**/*Application*, **/config/**, **/dto/**, **/generated/**)",
    "기본 패턴 + 추가 입력",
    "직접 전체 지정"
  ]
)
```

추가 패턴 입력:
```
AskUserQuestion(
  question="추가로 제외할 glob 패턴을 입력하세요 (쉼표 구분, 없으면 Enter).\n예: **/mapper/**, **/*Mapper*",
  options=["직접 입력", "없음"]
)
```

---

### 5단계: HarnessConfig 생성

인터뷰 결과와 입력된 `HarnessRequest` 기본값을 병합하여 `HarnessConfig` JSON을 생성한다.

```json
{
  "projectRoot": "<입력값 또는 현재 작업 디렉터리>",
  "specDocPaths": ["<인터뷰 (a) 결과>"],
  "targets": ["<인터뷰 (b) 결과>"],
  "targetModules": ["<인터뷰 (b) 결과>"],
  "buildTool": "<입력값 또는 미지정>",
  "junitPolicy": "jupiter-style",
  "testScope": "mixed",
  "javaVersion": "<입력값 또는 springProfile.javaBaseline>",
  "springVersion": "<입력값 또는 springProfile.bootVersion>",
  "springProfile": {
    "bootVersion": "<감지/인터뷰 결과>",
    "bootMajor": 4,
    "namespace": "jakarta",
    "junitEngine": "jupiter",
    "mockAnnotation": "MockitoBean",
    "mockImport": "org.springframework.test.context.bean.override.mockito.MockitoBean",
    "javaBaseline": 17,
    "gradleTestMode": "useJUnitPlatform",
    "degraded": false
  },
  "stylePolicy": "google-java",
  "lspAvailable": false,
  "maxRepairRetries": 2,
  "domainKeywords": [],
  "coverage": {
    "line": 0.95,
    "branch": 0.90,
    "method": 0.95,
    "class": 1.00,
    "excludes": [
      "**/*Application*",
      "**/config/**",
      "**/dto/**",
      "**/generated/**"
    ]
  },
  "mutation": {
    "mutators": "DEFAULTS",
    "targetClasses": [],
    "targetTests": [],
    "mutationThreshold": 0.80,
    "threads": 2
  },
  "coverageMaxIterations": 3,
  "mutationMaxIterations": 3
}
```

> **입력 키 매핑(필수)**: 이 `HarnessConfig`는 루프 스킬 입력 스키마와 **동일한 이름**을 쓴다 — `coverage{line,branch,method,class,excludes}`는 `measure-coverage`로, `mutation{...}`는 `mutation-test`로 그대로 전달된다(full-pipeline 0단계 산출과 일치). 반복 한도는 `full-pipeline`이 `coverageMaxIterations → measure-coverage.maxIterations`, `mutationMaxIterations → mutation-test.maxIterations`로 매핑한다(둘 다 고정 상한이 아니라 진전 추적 단위, fallback-policy.md #12).

#### 기본값 병합 우선순위

1. 인터뷰에서 명시적으로 입력된 값 (최우선)
2. 입력 `HarnessRequest`에 포함된 값
3. 위 기본값 (최하위)

---

### 6단계: 도메인 특화 스킬 스캐폴딩 (선택)

```
AskUserQuestion(
  question="이 프로젝트의 도메인 특화 테스트 단계를 재사용 가능한 스킬로 저장하시겠습니까?\n저장하면 /spring-test-harness:<name> 형식으로 언제든 호출할 수 있습니다.",
  options=["예, 스킬 이름 지정", "아니오, 건너뜀"]
)
```

"예" 선택 시:

```
AskUserQuestion(
  question="스킬 이름을 입력하세요 (소문자, 하이픈 허용, 영문).\n예: validate-order-domain, check-payment-flow",
  options=["직접 입력"]
)
```

입력받은 이름(`<skill-name>`)으로 `skills/<skill-name>/SKILL.md`를 생성한다.

#### 도메인 스킬 네이밍 규칙

- 네임스페이스: `/spring-test-harness:<skill-name>`
- 파일 위치: `skills/<skill-name>/SKILL.md`
- frontmatter: `name`, `description` 필드만 포함 (plugin 제약 준수)
- 본문: 현재 `HarnessConfig`를 기본 입력으로 포함하는 호출 절차

생성 예시 (`skills/validate-order-domain/SKILL.md`):

```markdown
---
name: validate-order-domain
description: 주문 도메인 특화 테스트 생성 및 커버리지 검증을 실행한다. "주문 도메인 테스트", "order 검증"처럼 주문 관련 테스트가 필요한 상황에서 자동 호출된다.
---

## 목적

주문 도메인(`com.example.order`)에 특화된 테스트 생성 파이프라인을 실행한다.
이 스킬은 `/spring-test-harness:full-pipeline`을 아래 HarnessConfig로 호출한다.

## 저장된 HarnessConfig

(configure-harness가 생성한 HarnessConfig JSON 삽입)

## 실행

/spring-test-harness:full-pipeline 을 위 HarnessConfig로 호출한다.
```

---

## 출력 (HarnessConfig)

`harnessConfig`의 전체 필드는 위 「5단계: HarnessConfig 생성」의 스키마와 동일하므로(중복 방지), 여기서는 출력 봉투(envelope)만 보인다.

```json
{
  "status": "ok",
  "summary": "인터뷰 완료. HarnessConfig 생성됨.",
  "harnessConfig": { "…": "「5단계: HarnessConfig 생성」 스키마와 동일 — 인터뷰 결과로 채워진 concrete 값" },
  "domainSkillCreated": null,
  "warnings": [],
  "errors": [],
  "nextActions": [
    "/spring-test-harness:full-pipeline 을 생성된 HarnessConfig로 실행하세요"
  ]
}
```

---

## 실패 처리

| 상황 | 처리 방식 |
|---|---|
| **필수 입력(projectRoot/buildTool/springVersion 등) 미지정 (#13)** | **자동 기본값 금지.** 대화형=`AskUserQuestion`으로 전부 질문 / CI=`status:"failed"`+remediation 중단 |
| **빌드도구 미감지 (#5)** | `detect_build_tool`이 `BUILD_TOOL_UNDETECTED`면, 대화형=`AskUserQuestion("gradle/maven?")` / CI=중단 |
| **빌드 능력 미비 (#17, 0.6단계)** | JaCoCo XML/PITest 미적용(`detect_build_capabilities.missing[]`). 대화형=`AskUserQuestion` 승인 후 스니펫 주입(`buildChanges[]`) / 거부 시 8·9단계 skipped / CI=자동 주입 금지·remediation 중단 |
| **콜드 의존성 캐시 (#18, 0.6단계)** | `check_dependency_cache.primed:false`. 대화형=`AskUserQuestion` 승인 후 `run_targeted_tests(online=True)` 1회 프라이밍 / CI=`BUILD_TEST_ALLOW_NETWORK=1` 옵트인·워밍업 안내 |
| 스펙 문서 경로가 존재하지 않음 | 대화형=계속할지 질문(#10) / CI=중단. (읽기불가 spec은 `ingest-specs`가 정책대로 처리) |
| 도메인 스킬 이름 중복 | `warnings`에 "이미 존재하는 스킬: {name}" 기록, 덮어쓰기 여부 재질문 |
| **CI 모드에서 필수 항목 누락** | **하드 중단** — `status:"failed"` + `errors`에 누락 항목과 remediation. 침묵 기본값 금지(fallback-policy.md 공통규칙 2) |

보안: 스킬 생성 시 `skills/` 디렉터리 내부에만 Write 수행. projectRoot 외부 경로 금지.
성능: 인터뷰 항목은 순차 진행. CI 모드에서는 즉시 반환.
