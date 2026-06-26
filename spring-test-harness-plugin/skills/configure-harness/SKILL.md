---
name: configure-harness
description: Spring 테스트 하네스 실행 전 인터랙티브 인터뷰를 수행하고 HarnessConfig JSON을 생성한다. "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "뮤테이션 설정", "하네스 구성"처럼 설정 또는 초기화가 필요한 상황에서 자동 호출된다. CI(claude -p)에서는 인터뷰를 건너뛰고 HarnessRequest JSON 기본값을 그대로 사용한다.
---

## 목적

먼저 대상의 **Spring Boot 버전 프로파일(Boot 2.0–4.x)을 감지/확정**(0.5단계, RESEARCH_NOTES §8)한 뒤, 사용자와 4항목 인터뷰(RESEARCH_NOTES §7)를 진행하여 `HarnessConfig` JSON을 생성한다. 생성된 `HarnessConfig`(`springProfile` 포함)는 `full-pipeline` 및 개별 스킬(measure-coverage, mutation-test 등)의 입력으로 사용된다.

**인터랙티브 CLI 전용 주의**: `AskUserQuestion`은 대화형 Claude Code CLI에서만 의미가 있다. `claude -p` 또는 CI 환경에서는 인터뷰를 건너뛰고 입력된 `HarnessRequest` JSON의 값과 아래 기본값을 병합하여 `HarnessConfig`를 생성한다.

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

### 0단계: 모드 판별

CI 모드 여부를 확인한다. CI 모드이면 인터뷰 단계(1~4)는 건너뛰되, **0.5단계(Spring 프로파일 감지)는 항상 수행**한다.

---

### 0.5단계: Spring 버전 프로파일 감지 (항상 수행 — Boot 2.0–4.x 하위호환)

테스트 관용구(네임스페이스·JUnit 엔진·Mock 애노테이션·Java 베이스라인)는 대상의 Spring Boot 버전에 따라 달라지므로, **인터뷰 전에 먼저 프로파일을 확정**한다. 근거·매트릭스: `[[../../RESEARCH_NOTES.md]]` §8, [references/version-compatibility.md](../../references/version-compatibility.md).

```
build-test-mcp.detect_spring_profile(root=projectRoot)
→ springProfile { bootVersion, bootMajor, namespace, junitEngine, mockAnnotation, mockImport, javaBaseline, gradleTestMode, degraded }
```

- **감지 성공(`degraded:false`)**: `springProfile`을 그대로 `HarnessConfig`에 채택. `notes`(네임스페이스/엔진 override)는 `warnings`에 전달.
- **감지 실패(`degraded:true`) + 대화형**: 아래 인터뷰로 사용자에게 직접 질문(사용자 결정사항: 미감지 시 인터뷰).

```
AskUserQuestion(
  question="대상 프로젝트의 Spring Boot 메이저 버전을 선택하세요. (빌드 파일에서 자동 감지하지 못했습니다)",
  options=["2.x (javax, Java 8)", "3.x (jakarta, Java 17)", "4.x (jakarta, 최신)", "모름 — 최신(4.x) 가정"]
)
```

  - 2.x 선택 시 후속 질문으로 JUnit 엔진을 확정한다(2.0–2.1은 기본 JUnit4):

```
AskUserQuestion(
  question="이 프로젝트의 테스트는 어떤 JUnit을 사용하나요?",
  options=["JUnit 5 (Jupiter, @Test/@DisplayName)", "JUnit 4 (@RunWith(SpringRunner.class)/org.junit.Test)", "모름 — 기존 테스트/빌드로 추정"]
)
```

  선택 결과로 `springProfile`을 구성한다: 2.x→`namespace=javax, mockAnnotation=MockBean, javaBaseline=8`; 3.0–3.3→`MockBean`; 3.4+/4.x→`MockitoBean, jakarta, java 17`. (정확한 import·게이트는 version-compatibility.md를 따른다.)

- **감지 실패 + CI**: `springProfile`을 latest(4.x: jakarta/jupiter/MockitoBean/Java17)로 가정하고 `warnings`에 "Spring 버전 미감지 — 최신(4.x) 프로파일 가정. 부정확하면 HarnessRequest.springVersion 명시 필요" 기록.

확정된 `springProfile`은 5단계 `HarnessConfig`에 포함되어 generate-scenarios/generate-tests/measure-coverage 전 단계로 전파된다.

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
    "기본 (mutators=DEFAULT, threshold=0.80)",
    "강화 (mutators=STRONGER, threshold=0.80)",
    "직접 지정"
  ]
)
```

"직접 지정" 선택 시 추가 질문:

```
AskUserQuestion(
  question="뮤테이터 세트를 선택하세요.",
  options=["DEFAULT", "STRONGER", "ALL"]
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

결과를 `mutationConfig`에 저장:
```json
{
  "mutators": "DEFAULT",
  "targetClasses": [],
  "mutationThreshold": 0.80,
  "maxIterations": 3
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
  "coverageGate": {
    "LINE": 0.95,
    "BRANCH": 0.90,
    "METHOD": 0.95,
    "CLASS": 1.00
  },
  "exclusionAllowlist": [
    "**/*Application*",
    "**/config/**",
    "**/dto/**",
    "**/generated/**"
  ],
  "mutationConfig": {
    "mutators": "DEFAULT",
    "targetClasses": [],
    "mutationThreshold": 0.80,
    "maxIterations": 3
  },
  "coverageMaxIterations": 3
}
```

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

```json
{
  "status": "ok",
  "summary": "인터뷰 완료. HarnessConfig 생성됨.",
  "harnessConfig": {
    "projectRoot": "/path/to/spring-project",
    "specDocPaths": ["docs/api-spec.md"],
    "targets": ["com.example.order"],
    "targetModules": [],
    "buildTool": "미지정",
    "junitPolicy": "jupiter-style",
    "testScope": "mixed",
    "javaVersion": "17",
    "springVersion": "4.1.0",
    "springProfile": {
      "bootVersion": "4.1.0",
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
    "coverageGate": {
      "LINE": 0.95,
      "BRANCH": 0.90,
      "METHOD": 0.95,
      "CLASS": 1.00
    },
    "exclusionAllowlist": [
      "**/*Application*",
      "**/config/**",
      "**/dto/**",
      "**/generated/**"
    ],
    "mutationConfig": {
      "mutators": "DEFAULT",
      "targetClasses": [],
      "mutationThreshold": 0.80,
      "maxIterations": 3
    },
    "coverageMaxIterations": 3
  },
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
| 인터뷰 중 사용자가 모든 항목을 건너뜀 | 기본값으로 `HarnessConfig` 생성, `warnings`에 "모든 항목이 기본값으로 설정됨" 기록 |
| 스펙 문서 경로가 존재하지 않음 | `warnings`에 경로 오류 기록, `specDocPaths`에서 제거 |
| 도메인 스킬 이름 중복 | `warnings`에 "이미 존재하는 스킬: {name}" 기록, 덮어쓰기 여부 재질문 |
| CI 모드에서 필수 항목 누락 | 기본값 사용, `warnings`에 기록 |

보안: 스킬 생성 시 `skills/` 디렉터리 내부에만 Write 수행. projectRoot 외부 경로 금지.
성능: 인터뷰 항목은 순차 진행. CI 모드에서는 즉시 반환.
