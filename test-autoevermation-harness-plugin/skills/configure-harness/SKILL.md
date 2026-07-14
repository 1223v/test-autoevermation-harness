---
name: configure-harness
description: Spring 테스트 하네스의 인터랙티브 인터뷰를 수행하고 HarnessConfig JSON을 생성한다. "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "뮤테이션 설정", "하네스 구성"처럼 설정 또는 초기화가 필요한 상황에서 자동 호출된다. 환경 세팅(Phase E)은 수행하지 않는다 — /test-autoevermation-harness-plugin:setup-harness 선행이 필수이며, 시작 시 E-verify 검증 프로브만 돌려 미완료면 하드 중단한다. CI(claude -p)에서는 인터뷰를 건너뛰되 미충족 필수 항목은 HarnessRequest 값으로 채우거나 중단한다.
---

## 목적

먼저 대상의 **Spring Boot 버전 프로파일(Boot 2.0–4.x)을 감지/확정**(0.5단계, RESEARCH_NOTES §8)한 뒤, 사용자와 4항목 인터뷰(RESEARCH_NOTES §7)를 진행하여 `HarnessConfig` JSON을 생성한다. 생성된 `HarnessConfig`(`springProfile` 포함)는 `full-pipeline` 및 개별 스킬(measure-coverage, mutation-test 등)의 입력으로 사용된다.

**선행 조건 — 환경 세팅은 이 스킬의 일이 아니다(v0.24.0)**: 환경 세팅(Phase E E1~E10 + 상태줄)의 수행 주체는 [`setup-harness`](../setup-harness/SKILL.md) 스킬이다. 이 스킬은 **어떤 항목도 세팅하지 않고**, 시작 시 **E-verify 검증 프로브**([references/environment-setup.md](../../references/environment-setup.md) 「E-verify 검증 프로브」, SSOT)만 실행해 세팅 완료 여부를 확인한다 — 미충족이면 `status:"failed"`로 **하드 중단**하고 `setup-harness` 실행을 안내한다(자동 세팅·자동 위임 없음).

**Fallback 정책 준수(필수)**: 런타임 의사결정은 [references/fallback-policy.md](../../references/fallback-policy.md)(SSOT)를 따른다. 미충족 조건(역량 미설치, 버전 미감지, 미지정 입력, 프로파일 충돌)은 **침묵 fallback·임의 기본값 없이** 처리한다 — **대화형은 `AskUserQuestion`으로 질문/함께 세팅**, **비대화형/CI는 결정적 항목 자동 세팅·그 외 하드 중단(remediation 안내)**.

**인터랙티브 CLI 전용 주의**: `AskUserQuestion`은 대화형 Claude Code CLI에서만 의미가 있다. `claude -p`/CI에서는 질문할 수 없으므로, **미충족 필수 조건이 있으면 `status:"failed"` + remediation으로 중단**한다(과거의 "인터뷰 스킵 + 기본값" 동작은 정책 변경으로 제거됨). 사용자는 `HarnessRequest`에 값을 미리 채워 중단을 피한다.

---

## 자동 호출 조건

- 사용자가 "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "뮤테이션 설정", "하네스 구성", "설정 인터뷰"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 0단계(전처리 이전)에서 `HarnessConfig`가 없을 때 선행 호출될 때
- 사용자가 `/test-autoevermation-harness-plugin:configure-harness`를 직접 실행할 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:configure-harness
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
- 이미 통과한 `_workspace/00_config-harness.json`(HarnessConfig)이 있어 재사용하는 경우 — 인터뷰를 재수행하지 않는다. 선택 필드 `mutation.enabled`가 없으면 `false`로 정규화한다.

CI 모드에서는 아래 단계별 절차 중 인터뷰 단계를 건너뛰고 바로 "HarnessConfig 생성" 단계로 이동한다.

---

## 단계별 절차

### Preflight 단계: 세팅 검증 게이트 (E-verify) — *검증만 한다, 세팅하지 않는다*

설정 시작 전에 [`setup-harness`](../setup-harness/SKILL.md)가 환경(E1~E10)을 이미 갖춰 놓았는지 **확인만** 한다. 정본 프로브 목록·판정 기준은 [references/environment-setup.md](../../references/environment-setup.md)(SSOT) 「**E-verify 검증 프로브**」 절이다 — 그 표를 Read해 그대로 실행한다.

프로브 요약(전부 부작용 없음·멱등·밀리초~1초):

1. **`health` 3종 실제 호출**(repo-ast·spec-doc·build-test) → E3b + 전이적으로 E1·E2·E3. repo-ast 응답의 `javaparser.jarFound`로 E6도 함께 확인.
2. `java -version` ≥ 21 → E4
3. `target/*-shaded.jar` 또는 `REPO_AST_JAVAPARSER_JAR` → E5·E6
4. `setup_jdtls.py --check-only` → E7 (감지만, 설치하지 않음)
5. 실행 JDK major ↔ Mockito/ByteBuddy 지원 범위 → E10

**게이트**: 프로브가 하나라도 실패하면 **대화형·CI 동일하게** `status:"failed"` + `errors`(실패 항목)로 **하드 중단**하고, remediation에 아래 고정 안내를 담는다. 0단계로 진행하지 않는다.

```
먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요
```

**금지 사항**: 프로브 실패를 스스로 고치지 않는다 — `--ensure-only`·`./mvnw package`·`setup_jdtls.py`(설치 모드) 실행 금지, `setup-harness` 자동 위임 금지, 정규식·AST-only degrade 금지. **세팅은 사용자가 명시적으로 `setup-harness`를 실행할 때만 일어난다.**

> **`lspAvailable`은 항상 `true`다** — E7(JDT LS)은 `setup-harness`의 필수 항목이고 E-verify 프로브가 이를 재확인하므로, `lspAvailable:false` 상태로 0단계에 진입하는 경로가 없다(근거: [setup-harness](../setup-harness/SKILL.md) E3b/E7 절). 아래 `HarnessConfig` 출력 예시의 `lspAvailable:true`는 이 전제의 결과다.

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

### 0.6단계: 빌드 능력 프로비저닝 + 캐시 프라이밍 (항상 수행 — 6/8단계 및 선택적 9단계 선행)

대상 빌드 파일이 **JaCoCo XML**을 낼 수 있는지 확인하고, 사용자가 PITest를 켠 경우에만 **PITest 플러그인·JUnit 어댑터·XML 출력**까지 확인한다. 의존성 캐시가 첫 오프라인 실행을 견디는지도 함께 확정한다. JaCoCo 에이전트는 `test` 실행 중 attach되므로 이 단계는 반드시 **6단계 run-tests 이전**에 끝낸다. 정본: [references/build-provisioning.md](../../references/build-provisioning.md), 정책: fallback-policy.md #17·#18.

**(a-0) PITest opt-in 확정.** `HarnessRequest.mutation.enabled`가 있으면 그 값을 사용한다. 없으면 대화형에서 아래 질문으로 인터뷰 항목 (c)의 첫 선택을 확정하고, 비대화형·CI에서는 선택 기능의 안전한 기본값인 `false`를 사용한다.

```
AskUserQuestion(
  question="PITest 뮤테이션 테스트를 사용할까요? 실행 시간이 크게 늘어날 수 있습니다.",
  options=["사용 안 함 (기본)", "사용함 — 설정과 빌드 능력 확인"]
)
```

- `사용 안 함` → `mutation.enabled:false`. PITest 관련 누락은 오류가 아니며 9단계가 `PITEST_DISABLED`로 정상 `skipped` 처리된다.
- `사용함` → `mutation.enabled:true`. 아래 능력 검사와 3단계 세부 설정을 수행한다.

**(a) 빌드 능력(E11, #17)** — `detect → approve → inject`

```
build-test-mcp.detect_build_capabilities(
  root=projectRoot,
  junit_engine=springProfile.junitEngine,
  require_pitest=mutation.enabled
)
→ { pitestRequired, capabilities{jacoco,jacocoXml,pitest,pitestJunit5,pitestXml}, missing[], proposedChanges[], remediation }
```

- `mutation.enabled:false`: `missing[]`에는 JaCoCo 필수 능력만 포함된다. PITest 플러그인이 없어도 `status:"ok"`일 수 있고 PITest 스니펫을 주입하지 않는다.
- `mutation.enabled:true`: PITest 플러그인·Jupiter 어댑터·`mutations.xml`을 위한 XML 출력도 `missing[]`에 포함한다.
- **누락(대화형)**: JaCoCo와 PITest 변경을 분리해 보여준다. 승인한 `proposedChanges[]`만 빌드 파일에 최소 주입(Edit)하고 `buildChanges[]`에 기록한 뒤 같은 `require_pitest` 값으로 재감지한다. 사용자가 **PITest 설정만** 거부하면 `mutation.enabled:false`로 바꾸고 `warnings:["PITEST_SETUP_DECLINED"]`를 남긴 뒤 8단계는 유지하고 9단계만 건너뛴다.
- **누락(CI)**: JaCoCo 누락, 또는 `mutation.enabled:true`로 명시했는데 PITest 능력이 누락된 경우에만 `status:"failed"` + 오류 코드·스니펫 remediation으로 중단한다. `mutation.enabled:false`이면 PITest 누락으로 중단하지 않는다.

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
  "예"면 6단계 첫 실행을 `run_targeted_tests(online=True)`로 1회 수행(또는 Maven `mvn dependency:go-offline`), 이후는 오프라인. "아니오"면 오프라인 그대로(실패 시 #18대로 보고). PITest가 비활성이고 JaCoCo 변경도 없었다면 PITest 때문에 프라이밍하지 않는다.
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

`mutation.enabled:false`이면 이 단계의 나머지 질문을 생략하고 기본 세부값은 저장만 한다(실행하지 않음). `mutation.enabled:true`일 때만 다음을 질문한다.

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
  "enabled": false,
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
  "lspAvailable": true,
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
    "enabled": false,
    "mutators": "DEFAULTS",
    "targetClasses": [],
    "targetTests": [],
    "mutationThreshold": 0.80,
    "threads": 2
  },
  "coverageMaxIterations": 3,
  "mutationMaxIterations": 3,
  "refactorAdvisory": {
    "enabled": true,
    "thresholds": { "cyclomatic": 10, "constructorArgs": 7 }
  }
}
```

> **입력 키 매핑(필수)**: 이 `HarnessConfig`는 루프 스킬 입력 스키마와 **동일한 이름**을 쓴다 — `coverage{line,branch,method,class,excludes}`는 `measure-coverage`로, `mutation{enabled,...}`는 `mutation-test`로 그대로 전달된다(full-pipeline 0단계 산출과 일치). `mutation.enabled`가 없으면 `false`로 정규화한다. 반복 한도는 `full-pipeline`이 `coverageMaxIterations → measure-coverage.maxIterations`, `mutationMaxIterations → mutation-test.maxIterations`로 매핑한다(둘 다 고정 상한이 아니라 진전 추적 단위, fallback-policy.md #12).
>
> **`refactorAdvisory`(선택)**: 3.5단계 리팩토링 권고 게이트 제어. **인터뷰 항목은 아니다**(비침습 기본값 — 질문 추가 없음). `HarnessRequest`로만 오버라이드하며, 기본값·임계값 의미론의 정본은 [refactor-advisory.md](../../references/refactor-advisory.md) §5.

#### 기본값 병합 우선순위

1. 인터뷰에서 명시적으로 입력된 값 (최우선)
2. 입력 `HarnessRequest`에 포함된 값
3. 위 기본값 (최하위)

---

### 6단계: 도메인 특화 스킬 스캐폴딩 (선택)

```
AskUserQuestion(
  question="이 프로젝트의 도메인 특화 테스트 단계를 재사용 가능한 스킬로 저장하시겠습니까?\n저장하면 /test-autoevermation-harness-plugin:<name> 형식으로 언제든 호출할 수 있습니다.",
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

- 네임스페이스: `/test-autoevermation-harness-plugin:<skill-name>`
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
이 스킬은 `/test-autoevermation-harness-plugin:full-pipeline`을 아래 HarnessConfig로 호출한다.

## 저장된 HarnessConfig

(configure-harness가 생성한 HarnessConfig JSON 삽입)

## 실행

/test-autoevermation-harness-plugin:full-pipeline 을 위 HarnessConfig로 호출한다.
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
    "/test-autoevermation-harness-plugin:full-pipeline 을 생성된 HarnessConfig로 실행하세요"
  ]
}
```

---

## 실패 처리

| 상황 | 처리 방식 |
|---|---|
| **E-verify 프로브 실패 (Preflight, #20)** | 대화형·CI 동일 `status:"failed"` + remediation `"먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요"`. **여기서 세팅하지 않는다**(자동 세팅·자동 위임·degrade 금지). 0단계 미진입 |
| **필수 입력(projectRoot/buildTool/springVersion 등) 미지정 (#13)** | **자동 기본값 금지.** 대화형=`AskUserQuestion`으로 전부 질문 / CI=`status:"failed"`+remediation 중단 |
| **빌드도구 미감지 (#5)** | `detect_build_tool`이 `BUILD_TOOL_UNDETECTED`면, 대화형=`AskUserQuestion("gradle/maven?")` / CI=중단 |
| **빌드 능력 미비 (#17, 0.6단계)** | JaCoCo XML은 필수 검사. PITest는 `mutation.enabled:true`일 때만 플러그인·JUnit 어댑터·XML을 필수 검사한다. 대화형=PITest 주입 거부 시 `enabled:false`로 전환해 9단계만 skipped / CI=명시적으로 활성화한 PITest 능력 누락일 때만 remediation 중단 |
| **콜드 의존성 캐시 (#18, 0.6단계)** | `check_dependency_cache.primed:false`. 대화형=`AskUserQuestion` 승인 후 `run_targeted_tests(online=True)` 1회 프라이밍 / CI=`BUILD_TEST_ALLOW_NETWORK=1` 옵트인·워밍업 안내 |
| 스펙 문서 경로가 존재하지 않음 | 대화형=계속할지 질문(#10) / CI=중단. (읽기불가 spec은 `ingest-specs`가 정책대로 처리) |
| 도메인 스킬 이름 중복 | `warnings`에 "이미 존재하는 스킬: {name}" 기록, 덮어쓰기 여부 재질문 |
| **CI 모드에서 필수 항목 누락** | **하드 중단** — `status:"failed"` + `errors`에 누락 항목과 remediation. 침묵 기본값 금지(fallback-policy.md 공통규칙 2) |

보안: 스킬 생성 시 `skills/` 디렉터리 내부에만 Write 수행. projectRoot 외부 경로 금지.
성능: 인터뷰 항목은 순차 진행. CI 모드에서는 즉시 반환.
