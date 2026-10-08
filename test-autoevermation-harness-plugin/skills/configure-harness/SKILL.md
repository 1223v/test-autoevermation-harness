---
name: configure-harness
description: Spring 테스트 하네스의 인터랙티브 인터뷰를 수행하고 HarnessConfig JSON을 생성한다. "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "하네스 구성"처럼 설정 또는 초기화가 필요한 상황에서 자동 호출된다. 환경 세팅(Phase E)은 수행하지 않는다 — /test-autoevermation-harness-plugin:setup-harness 선행이 필수이며, 시작 시 E-verify 검증 프로브만 돌려 미완료면 하드 중단한다. 명시적 비대화형 세션에서는 인터뷰를 건너뛰고 HarnessRequest 값으로 구성하되, 필수 항목이 비면 하드 중단한다.
---

## 실행 전 호스트 확인

[호스트 실행 계약](../../references/host-runtime.md)과 해당 호스트 문서, [근거 중심 작업 절차](../../references/evidence-workflow.md)를 먼저 읽는다. 아래 입력·출력과 검증 규칙은 공용이다. `Agent`·질문·LSP·훅·경로 예시는 Claude Code용이며, Codex는 호스트 문서의 순차 실행·질문 대기·JavaParser/소스 분석 경로로 치환한다.


## 목적

먼저 대상의 **Spring Boot 버전 프로파일(Boot 2.0–4.x)을 감지/확정**한 뒤, 사용자와 3항목 인터뷰를 진행하여 `schemaVersion:2`인 `HarnessConfig` JSON을 생성한다. 생성된 `HarnessConfig`(`springProfile` 포함)는 `full-pipeline` 및 `measure-coverage`의 입력으로 사용된다.

**선행 조건 — 환경 세팅은 이 스킬의 일이 아니다(v0.25.0)**: 환경 세팅(Phase E E1~E10 + 상태줄)의 수행 주체는 [`setup-harness`](../setup-harness/SKILL.md) 스킬이다. 이 스킬은 **어떤 항목도 세팅하지 않고**, 시작 시 **E-verify 검증 프로브**([references/environment-setup.md](../../references/environment-setup.md) 「E-verify 검증 프로브」, SSOT)만 실행해 세팅 완료 여부를 확인한다 — 미충족이면 `status:"failed"`로 **하드 중단**하고 `setup-harness` 실행을 안내한다(자동 세팅·자동 위임 없음).

**Fallback 정책 준수(필수)**: 런타임 의사결정은 [references/fallback-policy.md](../../references/fallback-policy.md)(SSOT)를 따른다. 미충족 조건(역량 미설치, 버전 미감지, 미지정 입력, 프로파일 충돌)은 **침묵 fallback·임의 기본값 없이** 처리한다 — **데이터 결정은 메인 대화에서 질문하고, E-verify 환경 미충족은 대화형·CI 모두 하드 중단한다**. 결정적 환경 설치는 setup-harness 소관이다.

**인터랙티브 CLI 전용 주의**: `AskUserQuestion`은 대화형 세션에서만 호출할 수 있다(판정 규칙은 아래 「인터랙티브 모드 감지」). 비대화형에서는 인터뷰를 건너뛰되, **필수 항목이 `HarnessRequest`에 없으면 `status:"failed"` + remediation으로 중단**한다 — 필수 항목을 임의 기본값으로 채우는 동작은 없다(문서화된 기본값이 있는 커버리지 임계값·제외 패턴만 기본값 사용). 사용자는 `HarnessRequest`에 값을 미리 채워 중단을 피한다.

---

## 자동 호출 조건

- 사용자가 "하네스 설정", "커버리지 임계값 설정", "테스트 대상 지정", "하네스 구성", "설정 인터뷰"와 같은 키워드를 사용할 때
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

**질문 경로**: 메인 대화가 현재 도구 목록과 호스트가 제공한 실행 모드를 확인한다. 명시적 `skipInterview:true` 또는 사용자 입력 호스트 없는 비대화형 실행에서는 요청값만 사용한다. 도구 목록에 `AskUserQuestion`이 **없는** 경우 호출하지 않는다. 가용성을 시험하려는 질문을 보내지 않는다. 실제 질문 거부·무응답은 승인 부재이며, CI 자동 승인으로 바꾸지 않고 중단한다. SDK `canUseTool` 입력 호스트는 공식 사용자 입력 경로로 처리한다([공식 문서](https://code.claude.com/docs/en/agent-sdk/user-input)).

아래 질문 예시는 **AskUserQuestion에 전달할 JSON 인자**다. 선택지의 직접 입력은 도구가 제공하는 자유 입력으로 받으며, Enter/취소를 동의로 해석하지 않는다.

**인터뷰 생략(비대화형과 별개)** — `schemaVersion:2`인 `_workspace/00_config-harness.json`(HarnessConfig)이 있어 재사용하는 경우 인터뷰를 재수행하지 않는다. 버전이 없거나 2가 아니면 구 설정으로 보고 재생성한다.

> **재사용해도 0.5단계는 건너뛰지 않는다.** 인터뷰만 생략할 뿐 Spring 프로파일은 **항상 재감지**한다(아래 0단계). 빌드 파일이 config보다 새로우면(`detect_pipeline_state`의 `staleness.buildFileNewerThanConfig:true`) 캐시된 `springProfile`은 신뢰할 수 없다 — Boot 2→3 업그레이드 하나로 javax↔jakarta·junit4↔jupiter·`@MockBean`↔`@MockitoBean`이 전부 뒤집히므로, 그 값으로 생성하면 컴파일되지 않거나 잘못된 관용구의 테스트가 나온다. 재감지 결과가 캐시와 다르면 `warnings`에 기록하고 새 값을 채택한다.

비대화형에서도 입력 확정·Preflight·0.5·0.6단계를 모두 수행한 뒤 인터뷰(1~3)만 생략한다. 이때 인터뷰가 채웠어야 할 **필수 항목**(`projectRoot`·`buildTool`·`springVersion`·`javaVersion` 등 #13 대상)이 `HarnessRequest`에 없으면 `status:"failed"` + `INTERVIEW_REQUIRED` + remediation으로 중단한다. 문서화된 기본값이 있는 항목(커버리지 임계값·제외 패턴)만 기본값을 쓴다.

---

## 단계별 절차

### 입력 확정 (프로브보다 먼저)

먼저 projectRoot를 요청/유효한 기존 설정에서 확정한다. 미지정이면 메인 대화가 질문하고, 입력 불가 모드면 INTERVIEW_REQUIRED로 중단한다. 확정된 절대 경로만 프로브에 전달한다. buildTool/javaVersion 미지정도 같은 정책으로 후보를 확인해 확정한다. Spring 버전은 0.5단계에서 실제 감지하되 충돌·미감지는 질문/중단한다. 기본값을 허용한 coverage 등만 기본값을 사용한다.

### Preflight 단계: 세팅 검증 게이트 (E-verify) — *검증만 한다, 세팅하지 않는다*

설정 시작 전에 [`setup-harness`](../setup-harness/SKILL.md)가 환경(E1~E10)을 이미 갖춰 놓았는지 **확인만** 한다. 정본 프로브 목록·판정 기준은 [references/environment-setup.md](../../references/environment-setup.md)(SSOT) 「**E-verify 검증 프로브**」 절이다 — 그 표를 Read해 그대로 실행한다.

프로브 요약(전부 부작용 없음·멱등·밀리초~1초):

1. **`health` 3종 실제 호출**(repo-ast·spec-doc·build-test) → E3b + 전이적으로 E1·E2·E3. repo-ast 응답의 `javaparser.jarFound`로 E6도 함께 확인.
2. `java -version` ≥ 21 → E4
3. repo-ast `health().javaparser`의 `jarFound:true` **그리고** `jarPersisted:true`(`${CLAUDE_PLUGIN_DATA}/javaparser/`에 영속된 jar) 또는 `REPO_AST_JAVAPARSER_JAR` 설정 → E5·E6. `jarPersisted:false`면 jar가 버전 키 캐시(`target/`)에만 있어 다음 업데이트에서 소실되므로 `persist_astcli_jar.py` 실행을 안내한다(environment-setup.md E-verify 표)
4. `setup_jdtls.py --check-only` → E7 (감지만, 설치하지 않음)
5. 실행 JDK major ↔ Mockito/ByteBuddy 지원 범위 → E10
6. **`projectRoot` 범위 대조** — `repo-ast.health()`의 `allowRoot`와 확정된 `projectRoot`를 대조한다. `.mcp.json`이 `REPO_AST_ALLOW_ROOT=${CLAUDE_PROJECT_DIR}`로 고정하므로 `projectRoot`가 그 밖이면 repo-ast가 모든 경로를 `denied`로 응답해 AST 분석이 조용히 비게 된다. 벗어나면 `status:"failed"` + remediation(① 대상 프로젝트에서 세션 열기 / ② `REPO_AST_ALLOW_ROOT` 지정 후 `/reload-plugins`)으로 중단한다. `allowRoot`가 `null`이면 서버가 cwd로 폴백하므로 동일하게 대조한다.

**게이트**: 프로브가 하나라도 실패하면 **대화형·CI 동일하게** `status:"failed"` + `errors`(실패 항목)로 **하드 중단**하고, remediation에 아래 고정 안내를 담는다. 0단계로 진행하지 않는다.

```
먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요
```

**금지 사항**: 프로브 실패를 스스로 고치지 않는다 — `--ensure-only`·`./mvnw package`·`setup_jdtls.py`(설치 모드) 실행 금지, `setup-harness` 자동 위임 금지, 정규식·AST-only degrade 금지. **프로젝트 환경 세팅은 setup-harness에서 수행한다. SessionStart의 Python/MCP 자동 부트스트랩은 별도의 플러그인 기동 절차다.**

> **LSP 검증**: 바이너리·설정 존재는 연결 증거가 아니다. 현재 세션의 공식 LSP 도구로 대상 Java 파일의 documentSymbol 조회를 성공시킨 뒤에만 lspAvailable:true와 조회 파일·operation을 evidence에 기록한다. 도구/연결 미가용이면 JDT_LS_UNAVAILABLE로 중단한다.

### 0단계: 모드 판별

비대화형 모드 여부를 확인한다(「인터랙티브 모드 감지」). 비대화형이면 인터뷰 단계(1~3)는 건너뛰되, **0.5단계(Spring 프로파일 감지)는 항상 수행**한다.

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
{
  "questions": [
    {
      "question": "대상 프로젝트의 정확한 Spring Boot 버전(예: 3.3.13 또는 3.4.5)을 자유 입력하세요. (빌드 파일에서 자동 감지하지 못했습니다)",
      "header": "하네스 설정",
      "options": [
        {
          "label": "정확한 버전 직접 입력",
          "description": "정확한 버전 직접 입력"
        },
        {
          "label": "빌드 파일 확인 후 재시도",
          "description": "빌드 파일 확인 후 재시도"
        },
        {
          "label": "중단",
          "description": "중단"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

  정확한 버전으로 매트릭스를 적용하고 필요한 경우 JUnit 엔진을 후속 질문으로 확정(2.0–2.1 기본 JUnit4):

```
{
  "questions": [
    {
      "question": "이 프로젝트의 테스트는 어떤 JUnit을 사용하나요?",
      "header": "하네스 설정",
      "options": [
        {
          "label": "JUnit 5 (Jupiter, @Test/@DisplayName)",
          "description": "JUnit 5 (Jupiter, @Test/@DisplayName)"
        },
        {
          "label": "JUnit 4 (@RunWith(SpringRunner.class)/org.junit.Test)",
          "description": "JUnit 4 (@RunWith(SpringRunner.class)/org.junit.Test)"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

  선택 결과로 `springProfile` 구성(2.x→`javax/MockBean/Java8`; 3.0–3.3→`MockBean`; 3.4+/4.x→`MockitoBean/jakarta/Java17`; import·게이트는 version-compatibility.md).
  - **CI**: 가정 금지. `status:"failed"`, `errors`에 `INTERVIEW_REQUIRED` + "HarnessRequest.springVersion을 명시하세요". 중단.

- **프로파일 충돌(`requiresConfirmation:true`) (#6)**: 빌드파일 값과 소스/기존테스트 값이 다르다(`conflicts[]`). **자동 적용 금지.**
  - 대화형: 각 충돌(namespace/junitEngine)에 대해 어느 쪽을 따를지 질문 후 확정.

```
{
  "questions": [
    {
      "question": "감지 충돌: namespace가 빌드파일=<buildFileValue> vs 소스=<sourceValue> 입니다. 어느 것을 사용할까요?",
      "header": "하네스 설정",
      "options": [
        {
          "label": "빌드파일 값(<buildFileValue>)",
          "description": "빌드파일 값(<buildFileValue>)"
        },
        {
          "label": "소스 값(<sourceValue>)",
          "description": "소스 값(<sourceValue>)"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

  - CI: `status:"failed"`, `errors`에 `PROFILE_CONFLICT` + 충돌 내용. 중단.

확정된 `springProfile`은 4단계 `HarnessConfig`에 포함되어 generate-scenarios/generate-tests/measure-coverage 전 단계로 전파된다.

---

### 0.6단계: 빌드 능력 프로비저닝 + 캐시 프라이밍 (항상 수행 — 6/8단계 선행)

대상 빌드 파일이 **JaCoCo XML**을 생성할 수 있는지 확인하고, 의존성 캐시가 첫 오프라인 실행을 견디는지도 함께 확정한다. JaCoCo 에이전트는 `test` 실행 중 attach되므로 이 단계는 반드시 **6단계 run-tests 이전**에 끝낸다. 정본: [references/build-provisioning.md](../../references/build-provisioning.md), 정책: fallback-policy.md #17·#18.

**(a) 빌드 능력(E11, #17)** — `detect → approve → inject`

```
build-test-mcp.detect_build_capabilities(root=projectRoot)
→ { capabilities{jacoco,jacocoXml}, missing[], proposedChanges[], remediation }
```

- **누락(대화형)**: JaCoCo 변경안을 보여주고, 승인한 `proposedChanges[]`만 빌드 파일에 최소 주입(Edit)한 뒤 `buildChanges[]`에 기록하고 재감지한다.
- **누락(CI)**: `status:"failed"` + 오류 코드·스니펫 remediation으로 중단한다. 커버리지 XML 없이 8단계로 진행하지 않는다.

**(b) 캐시 프라이밍(E12, #18)**
```
build-test-mcp.check_dependency_cache(build_tool=buildTool, root=projectRoot) → { primed, primeCommand, recommendation }
```
- **대화형**: `primed:false`이거나 방금 (a)에서 플러그인을 주입했다면 →
```
{
  "questions": [
    {
      "question": "의존성/플러그인을 1회 온라인으로 받아올까요? (이후 실행은 오프라인 유지)",
      "header": "하네스 설정",
      "options": [
        {
          "label": "예 — 1회 온라인 프라이밍",
          "description": "예 — 1회 온라인 프라이밍"
        },
        {
          "label": "아니오 — 오프라인 진행(실패 위험)",
          "description": "아니오 — 오프라인 진행(실패 위험)"
        }
      ],
      "multiSelect": false
    }
  ]
}
```
  "예"면 6단계 첫 실행을 `run_targeted_tests(online=True)`로 1회 수행(또는 Maven `mvn dependency:go-offline`), 이후는 오프라인. "아니오"면 오프라인 그대로 진행하고 실패 시 #18대로 보고한다.
- **CI**: 자동 온라인 전환 금지 — `BUILD_TEST_ALLOW_NETWORK=1` 옵트인 또는 사전 캐시 워밍업을 안내. 미충족이면 첫 실행 실패를 `partial`로 보고.

감지·주입·프라이밍 결과는 `_workspace/00b_build_provision.json`에 보존한다(부분 재실행 시 재사용, 중복 주입 금지).

---

### 1단계: 인터뷰 항목 (a) — 스펙 문서 경로

```
{
  "questions": [
    {
      "question": "테스트 생성에 참고할 스펙 문서 경로가 있으면 입력하세요 (없으면 Enter로 건너뜁니다).\n예: docs/api-spec.md, requirements/order-spec.md",
      "header": "하네스 설정",
      "options": [
        {
          "label": "경로 직접 입력",
          "description": "경로 직접 입력"
        },
        {
          "label": "건너뜀 (스펙 없이 진행)",
          "description": "건너뜀 (스펙 없이 진행)"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

- 입력값을 `specDocPaths[]`에 추가한다.
- 여러 경로를 쉼표로 구분해 입력할 수 있다.
- 건너뜀 선택 시 `specDocPaths: []`로 설정하고 `warnings`에 "스펙 문서 미지정 — ingest-specs가 partial로 실행됩니다" 추가.

---

### 2단계: 인터뷰 항목 (b) — 테스트 생성 대상

```
{
  "questions": [
    {
      "question": "테스트를 생성할 대상을 지정하세요. 패키지, 클래스 FQCN, 또는 모듈명을 입력할 수 있습니다 (없으면 자동 탐지).\n예: com.example.order, com.example.payment.PaymentService",
      "header": "하네스 설정",
      "options": [
        {
          "label": "직접 입력",
          "description": "직접 입력"
        },
        {
          "label": "자동 탐지 (전체 Spring 컴포넌트 스캔)",
          "description": "자동 탐지 (전체 Spring 컴포넌트 스캔)"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

- 입력값을 `targets[]`에 추가한다.
- 자동 탐지 선택 시 `targets: []`로 설정 — analyze-ast 단계에서 `list_spring_components`로 자동 탐색.
- 멀티 모듈 프로젝트의 경우 모듈명을 입력받아 `targetModules[]`에 추가.

```
{
  "questions": [
    {
      "question": "멀티 모듈 프로젝트라면 대상 모듈명을 입력하세요 (단일 모듈이면 건너뜁니다).\n예: order-service, payment-service",
      "header": "하네스 설정",
      "options": [
        {
          "label": "모듈명 입력",
          "description": "모듈명 입력"
        },
        {
          "label": "단일 모듈 / 건너뜀",
          "description": "단일 모듈 / 건너뜀"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

---

### 3단계: 인터뷰 항목 (c) — 커버리지 임계값 + 제외 규칙

```
{
  "questions": [
    {
      "question": "커버리지 게이트 임계값을 설정하세요.",
      "header": "하네스 설정",
      "options": [
        {
          "label": "기본값 사용 (LINE=0.95, BRANCH=0.90, METHOD=0.95, CLASS=1.00)",
          "description": "기본값 사용 (LINE=0.95, BRANCH=0.90, METHOD=0.95, CLASS=1.00)"
        },
        {
          "label": "직접 지정",
          "description": "직접 지정"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

"직접 지정" 선택 시 각 카운터별 추가 질문:

```
{
  "questions": [
    {
      "question": "LINE 커버리지 목표를 입력하세요 (기본: 0.95)",
      "header": "하네스 설정",
      "options": [
        {
          "label": "0.95",
          "description": "0.95"
        },
        {
          "label": "0.90",
          "description": "0.90"
        },
        {
          "label": "0.85",
          "description": "0.85"
        },
        {
          "label": "직접 입력",
          "description": "직접 입력"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

(BRANCH, METHOD, CLASS도 동일 패턴으로 질문)

```
{
  "questions": [
    {
      "question": "커버리지 게이트에서 제외할 패턴을 선택하거나 추가하세요.",
      "header": "하네스 설정",
      "options": [
        {
          "label": "기본 제외 패턴 사용 (**/*Application*, **/config/**, **/dto/**, **/generated/**)",
          "description": "기본 제외 패턴 사용 (**/*Application*, **/config/**, **/dto/**, **/generated/**)"
        },
        {
          "label": "기본 패턴 + 추가 입력",
          "description": "기본 패턴 + 추가 입력"
        },
        {
          "label": "직접 전체 지정",
          "description": "직접 전체 지정"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

추가 패턴 입력:
```
{
  "questions": [
    {
      "question": "추가로 제외할 glob 패턴을 입력하세요 (쉼표 구분, 없으면 Enter).\n예: **/mapper/**, **/*Mapper*",
      "header": "하네스 설정",
      "options": [
        {
          "label": "직접 입력",
          "description": "직접 입력"
        },
        {
          "label": "없음",
          "description": "없음"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

---

### 4단계: HarnessConfig 생성

인터뷰 결과와 입력된 `HarnessRequest` 기본값을 병합하여 `HarnessConfig` JSON을 생성한다. 선택 메타데이터 `host`(`claude-code`/`codex`)와 `analysisBackend`(`javaparser-lsp`/`javaparser-source`)를 함께 기록할 수 있다. 아래는 실제 LSP 연결이 확인된 Claude 예시다. Codex는 `host:"codex"`, `analysisBackend:"javaparser-source"`, `lspAvailable:false`를 사용한다. schemaVersion과 기존 산출물 구조는 바꾸지 않는다.

```json
{
  "schemaVersion": 2,
  "projectRoot": "<입력값 — 미지정이면 대화형 질문 / 비대화형 중단(#13), 자동 cwd 금지>",
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
  "maxRepairRetries": 3,
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
  "coverageMaxIterations": 3,
  "refactorAdvisory": {
    "enabled": true,
    "thresholds": { "cyclomatic": 10, "constructorArgs": 7 }
  }
}
```

> **입력 키 매핑(필수)**: `coverage{line,branch,method,class,excludes}`는 `measure-coverage`로 그대로 전달하며, `coverageMaxIterations`는 `measure-coverage.maxIterations`로 매핑한다(고정 상한이 아니라 진전 추적 단위, fallback-policy.md #12). `schemaVersion`은 항상 `2`다.
>
> **`refactorAdvisory`(선택)**: 3.5단계 리팩토링 권고 게이트 제어. **인터뷰 항목은 아니다**(비침습 기본값 — 질문 추가 없음). `HarnessRequest`로만 오버라이드하며, 기본값·임계값 의미론의 정본은 [refactor-advisory.md](../../references/refactor-advisory.md) §5.

#### 기본값 병합 우선순위

1. 인터뷰에서 명시적으로 입력된 값 (최우선)
2. 입력 `HarnessRequest`에 포함된 값
3. 위 기본값 (최하위)

---

### 5단계: 도메인 특화 스킬 스캐폴딩 (선택)

```
{
  "questions": [
    {
      "question": "이 프로젝트의 도메인 특화 테스트 단계를 재사용 가능한 스킬로 저장하시겠습니까?\n저장하면 /<name> 형식으로 언제든 호출할 수 있습니다.",
      "header": "하네스 설정",
      "options": [
        {
          "label": "예, 스킬 이름 지정",
          "description": "예, 스킬 이름 지정"
        },
        {
          "label": "아니오, 건너뜀",
          "description": "아니오, 건너뜀"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

"예" 선택 시:

```
{
  "questions": [
    {
      "question": "스킬 이름을 입력하세요 (소문자, 하이픈 허용, 영문).\n예: validate-order-domain, check-payment-flow",
      "header": "하네스 설정",
      "options": [
        {
          "label": "직접 입력",
          "description": "직접 입력"
        },
        {
          "label": "취소",
          "description": "취소"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

입력받은 이름(`<skill-name>`)으로 `<projectRoot>/.claude/skills/<skill-name>/SKILL.md`를 생성한다.

#### 도메인 스킬 네이밍 규칙

- 네임스페이스: `/<skill-name>`
- 파일 위치: `<projectRoot>/.claude/skills/<skill-name>/SKILL.md`
- frontmatter: `name`, `description` 필드만 포함 (plugin 제약 준수)
- 본문: 현재 `HarnessConfig`를 기본 입력으로 포함하는 호출 절차

생성 예시 (`<projectRoot>/.claude/skills/validate-order-domain/SKILL.md`):

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

`harnessConfig`의 전체 필드는 위 「4단계: HarnessConfig 생성」의 스키마와 동일하므로(중복 방지), 여기서는 출력 봉투(envelope)만 보인다.

```json
{
  "status": "ok",
  "summary": "인터뷰 완료. HarnessConfig 생성됨.",
  "harnessConfig": { "…": "「4단계: HarnessConfig 생성」 스키마와 동일 — 인터뷰 결과로 채워진 concrete 값" },
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
| **빌드도구 미감지 (#5)** | `detect_build_tool`이 `BUILD_TOOL_UNDETECTED`면, 대화형=`AskUserQuestion으로 “gradle/maven?” 질문` / CI=중단 |
| **빌드 능력 미비 (#17, 0.6단계)** | JaCoCo XML을 필수 검사한다. 대화형=변경안 승인 후 최소 주입·재감지 / CI=`status:"failed"`+remediation 중단 |
| **콜드 의존성 캐시 (#18, 0.6단계)** | `check_dependency_cache.primed:false`. 대화형=`AskUserQuestion` 승인 후 `run_targeted_tests(online=True)` 1회 프라이밍 / CI=`BUILD_TEST_ALLOW_NETWORK=1` 옵트인·워밍업 안내 |
| 스펙 문서 경로가 존재하지 않음 | 대화형=계속할지 질문(#10) / CI=중단. (읽기불가 spec은 `ingest-specs`가 정책대로 처리) |
| 도메인 스킬 이름 중복 | `warnings`에 "이미 존재하는 스킬: {name}" 기록, 덮어쓰기 여부 재질문 |
| **CI 모드에서 필수 항목 누락** | **하드 중단** — `status:"failed"` + `errors`에 누락 항목과 remediation. 침묵 기본값 금지(fallback-policy.md 공통규칙 2) |

보안: 스킬 이름은 `[a-z][a-z0-9-]*`로 검증하고 예약 이름 synced를 거부한다. 스킬 생성 시 projectRoot의 `.claude/skills/` 내부에만 Write하며 realpath로 symlink 이탈도 검사한다. projectRoot 외부 경로 금지.
성능: 인터뷰 항목은 순차 진행. CI에서도 필수 검증 프로브 후 반환한다.
