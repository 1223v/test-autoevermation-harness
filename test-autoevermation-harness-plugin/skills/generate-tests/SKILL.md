---
name: generate-tests
description: 시나리오 집합을 받아 JUnit Jupiter/Spring Test/Mockito 기반의 컴파일 가능한 테스트 코드를 작성하고 빌드 설정 변경안을 제안한다. "테스트 코드 생성", "테스트 작성", "JUnit 생성"처럼 테스트 파일 생성이 필요한 상황에서 자동 호출된다.
---

## 목적

`generate-scenarios` 결과(ScenarioSet)를 받아 각 시나리오에 대응하는 테스트 클래스·메서드를 작성한다. 컨트롤러는 `@WebMvcTest + MockMvc`, JPA 레포는 `@DataJpaTest`, 서비스/순수 로직은 스프링 컨텍스트 없는 단위 테스트, 다계층 통합은 `@SpringBootTest`(최소화) 방식을 따른다.

**버전 인식(Boot 2.0–4.x)**: 협력 빈 Mock 애노테이션·네임스페이스·JUnit 엔진은 `HarnessConfig.springProfile`에 따라 분기한다 — `mockAnnotation`(`@MockBean`/`@MockitoBean`)과 정확한 `mockImport`, `namespace`(javax/jakarta), `junitEngine`(junit4/jupiter)을 그대로 적용한다. 전체 코드 템플릿은 [references/version-compatibility.md](../../references/version-compatibility.md), 매트릭스는 `[[../../RESEARCH_NOTES.md]]` §8. Google Java Style을 준수하며 import를 완결한다. 결과 파일은 `run-tests` 스킬로 전달된다.

---

## MCP 필수 (대체 금지)

이 스킬은 `repo-ast` + `build-test` MCP 도구가 **필수**다. 미가용 시 처리(Grep/Read/직접 파싱 대체 금지 · `status:"failed"`+remediation · 즉시 중단)는 [fallback-policy.md](../../references/fallback-policy.md) #20을 그대로 따른다 — 연결은 `setup-harness`(E3b)가 세팅·검증하고, 파이프라인 시작 전 E-verify 프로브(`health` 3종 호출)가 재확인한다.

---

## 자동 호출 조건

- 사용자가 "테스트 코드 생성", "테스트 작성", "JUnit 생성", "테스트 파일 만들기"와 같은 키워드를 사용할 때
- `full-pipeline` 스킬의 5단계(시나리오 확정 후)에서 순차 호출될 때

## 수동 호출 예시

```
/test-autoevermation-harness-plugin:generate-tests
```

입력 JSON을 별도로 전달하는 경우:

```json
{
  "scenarios": [...],
  "buildTool": "gradle",
  "springProfile": { "bootMajor": 2, "namespace": "javax", "junitEngine": "jupiter", "mockAnnotation": "MockBean", "mockImport": "org.springframework.boot.test.mock.mockito.MockBean", "javaBaseline": 8, "gradleTestMode": "useJUnitPlatform" },
  "junitPolicy": "jupiter-style",
  "stylePolicy": "google-java"
}
```

---

## 입력

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `scenarios` | `Scenario[]` | 예 | — | `generate-scenarios` 출력의 `scenarios` 배열 |
| `buildTool` | `string` | 아니오 | `"미지정"` → auto-detect | `gradle` 또는 `maven` |
| `springProfile` | `object` | 아니오 | `detect_spring_profile` 결과 | Boot 2.0–4.x 프로파일. 미지정 시 build-test-mcp로 감지 |
| `junitPolicy` | `string` | 아니오 | `"jupiter-style"` | `jupiter-style`(BOM 위임) 또는 `strict-5x`(정책 예외, 명시 필요) |
| `stylePolicy` | `string` | 아니오 | `"google-java"` | 코드 스타일 정책 |
| `astResult` | `AstAnalysisResult` | 아니오 | `null` | 메서드 시그니처 확인용 |
| `projectRoot` | `string` | 아니오 | 현재 작업 디렉터리 | 프로젝트 루트 절대 경로 — 절대경로 파일 출력의 기준 |
| `testSourceRoot` | `string` | 아니오 | `{projectRoot}/src/test/java` | 테스트 소스 루트 |

`junitPolicy: "strict-5x"` 사용 시 빌드 파일에 명시적 version pin과 CHANGELOG 경고를 `buildChanges`에 포함한다.

---

## 단계별 절차

1. **입력 검증**
   - `scenarios`가 비어 있으면 `status: "failed"`, `errors: ["시나리오 없음 — generate-scenarios 실행 필요"]` 반환.
   - `buildTool`이 `"미지정"`이면 `build-test-mcp.detect_build_tool`로 auto-detect.
   - `junitPolicy: "strict-5x"` 감지 시 `warnings`에 "BOM 기본값(Jupiter 6.0.x)과의 충돌 주의, 명시적 version pin 필요" 추가.

2. **subagent 호출**

   ```
   Task(
     subagent_type="test-code-generator",
     model="inherit",
     prompt="""
   다음 시나리오 집합으로 테스트 코드를 작성하라.

   입력:
   {
     "scenarios": <scenarios>,
     "buildTool": <buildTool>,
     "springProfile": <springProfile>,
     "junitPolicy": <junitPolicy>,
     "stylePolicy": <stylePolicy>,
     "astResult": <astResult>,
     "projectRoot": <projectRoot>,
     "testSourceRoot": <testSourceRoot 또는 {projectRoot}/src/test/java>
   }

   springProfile(버전 분기 — Boot 2.0–4.x):
   - springProfile이 입력에 없으면 build-test-mcp.detect_spring_profile(projectRoot)로 먼저 감지하라.
   - mockAnnotation/mockImport를 그대로 사용: @MockBean(Boot ≤3.3) 또는 @MockitoBean(3.4+/4.x).
     · @MockBean import = org.springframework.boot.test.mock.mockito.MockBean
     · @MockitoBean import = org.springframework.test.context.bean.override.mockito.MockitoBean
   - namespace 적용: 엔티티/검증/서블릿 타입은 javax.*(Boot 2.x) 또는 jakarta.*(3.x+). 대상 소스의 실제 import를 우선.
   - junitEngine 분기:
     · jupiter → org.junit.jupiter.api.Test + @DisplayName(한국어), 순수 단위는 @ExtendWith(MockitoExtension.class), 빌드 useJUnitPlatform().
     · junit4 → @RunWith(SpringRunner.class)(슬라이스/컨텍스트) 또는 @RunWith(MockitoJUnitRunner.class)(순수 단위), org.junit.Test, public void 메서드, @DisplayName 미사용(메서드명으로 의도 표현), 빌드 useJUnit()(2.0/2.1) 또는 junit-vintage 안내.
   - 정확한 import·전체 템플릿은 references/version-compatibility.md를 따른다.

   코드 생성 규칙:
   - 클래스 네이밍: <Target>Test (단위/슬라이스), <Target>IT (통합/Failsafe).
   - 메서드 네이밍(필수): <scenarioRefSlug>_<행위> 형식으로 scenarioRef 포함. scenarioRefSlug=ref 소문자+영숫자만(SC-001→sc001). 예: sc001_listActiveOrders_returnsOkJson.
   - BDD 본문(필수): // given(stub/입력) → // when(단일 행위 호출, 결과 캡처) → // then(단언) 3단 섹션. 시나리오의 given/when/then 필드를 1:1 반영. 예외 검증은 // when & then(assertThrows/assertThatThrownBy) 병합 허용. 협력 stub은 BDDMockito given().willReturn()/willThrow().
   - 패키지: 대상과 동일 패키지의 src/test/java.
   - 컨트롤러 → @WebMvcTest + MockMvc + 협력 빈은 springProfile.mockAnnotation.
   - JPA 레포 → @DataJpaTest (junit4면 @RunWith(SpringRunner.class) 동반).
   - 서비스/순수 로직 → 스프링 컨텍스트 없는 단위 테스트.
   - 다계층 통합 → @SpringBootTest (꼭 필요할 때만).
   - 협력 빈 대체: springProfile.mockAnnotation을 import와 함께 정확히 사용(프로파일과 무관한 임의 고정 금지).
   - fixture: 테스트 데이터 빌더(<Type>Fixtures/<Type>Builder) 우선, 매직값 금지.
   - 동치류/경계값 3개 이상 → @ParameterizedTest (jupiter). junit4면 @RunWith(Parameterized.class) 또는 데이터 루프.
   - 각 테스트 메서드 javadoc에 scenarioRef/criteriaRef 기록.
   - Google Java Style 준수, import 완결.
   - 실제 네트워크/Thread.sleep/broad catch 금지.
   - junitPolicy가 strict-5x이면 빌드 파일에 명시적 version pin 추가(jupiter 프로파일 한정).
   - astResult에서 메서드 시그니처를 확인해 unresolved 시그니처는 생성 보류 + warnings 기록.
   - repo-ast-mcp로 시그니처를 재확인하고, build-test-mcp로 의존성/스타일을 검증하라.
   - 시나리오 target 호출 자가 검증(필수 게이트): 각 파일 기록 후 parse_java_file의 methodCalls로
     각 scNNN_ 메서드가 시나리오 target(FQCN#method) 메서드를 실제 호출하는지 대조하라.
     · unit/직접호출: target 메서드 단순명 ∈ methodCalls → targetCallCheck: "matched".
     · slice/integration(MockMvc 등): when의 HTTP verb/경로 ↔ perform(...) 요청, given의 협력자
       stub 메서드명 ∈ methodCalls를 체크리스트로 대조, evidence 기록 → "manual-verified".
     · 불일치: // when을 target에 맞게 1회 자가 수정 후 재검증. 여전히 불일치면 파일을 결과에서
       제외(기록했다면 삭제)하고 warnings에 SCENARIO_TARGET_MISMATCH 기록, status: partial.
   - 결과를 아래 JSON 스키마에 맞게 반환하라. files[] 모든 항목에 targetCallCheck는 필수다.

   출력 스키마:
   {
     "status": "ok" | "partial" | "failed",
     "summary": string,
     "files": [
       {
         "path": string,
         "content": string,
         "scenarioRef": string,
         "testClass": string,
         "targetCallCheck": "matched" | "manual-verified" | "mismatch"
       }
     ],
     "buildChanges": [string],
     "rationale": [string],
     "evidence": [string],
     "warnings": [string],
     "errors": [string],
     "nextActions": [string]
   }
   """
   )
   ```

3. **결과 검증**
   - `files`가 비어 있으면 `status: "failed"`.
   - `files[]` 중 `targetCallCheck`가 없거나 `"mismatch"`인 항목은 Write 대상에서 제외하고 해당 시나리오를 `warnings`(`SCENARIO_TARGET_MISMATCH`)로 보고한다 — 필드 누락은 게이트 미수행으로 간주한다.
   - `warnings`에 "UNRESOLVED_SIGNATURE" 항목이 있으면 해당 시나리오는 생성 보류로 표기하고 `nextActions`에 AST 보강 안내 추가.
   - `buildChanges`에 `strict-5x` pin이 포함된 경우 `warnings`에 버전 충돌 위험 문구 추가.

4. **파일 쓰기**
   - `files[]`의 각 항목을 `path` 경로에 Write한다.
   - 이미 존재하는 파일은 덮어쓰기 전 사용자에게 확인을 요청한다.

5. **결과 반환**
   - `TestGenResult` JSON(파일 목록 + buildChanges)을 메인 세션으로 반환한다.

---

## 출력 (TestGenResult)

```json
{
  "status": "ok",
  "summary": "3개 테스트 파일 생성 완료",
  "files": [
    {
      "path": "src/test/java/com/example/order/OrderServiceTest.java",
      "content": "...",
      "scenarioRef": "SC-001",
      "testClass": "com.example.order.OrderServiceTest",
      "targetCallCheck": "matched"
    },
    {
      "path": "src/test/java/com/example/order/OrderControllerTest.java",
      "content": "...",
      "scenarioRef": "SC-002",
      "testClass": "com.example.order.OrderControllerTest",
      "targetCallCheck": "manual-verified"
    }
  ],
  "buildChanges": [
    "build.gradle.kts: springProfile.gradleTestMode(useJUnitPlatform/useJUnit) 확인, testLogging 추가"
  ],
  "rationale": [
    "SC-001: 외부 DB mock으로 단위 테스트 가능, 스프링 컨텍스트 불필요",
    "SC-002: 컨트롤러 요청/응답 검증은 @WebMvcTest 슬라이스가 최적"
  ],
  "evidence": [],
  "warnings": [],
  "errors": [],
  "nextActions": []
}
```

---

## 실패 처리

| 오류 코드 | 발생 조건 | 처리 방식 |
|---|---|---|
| `UNRESOLVED_SIGNATURE` | astResult에 미해석 시그니처 | 해당 시나리오 생성 보류 + `warnings` 기록 |
| `SCENARIO_TARGET_MISMATCH` | 생성 테스트가 시나리오 `target` 메서드를 호출하지 않음(자가 수정 1회 후에도) | 해당 파일 제외 + `warnings` 기록, `status: "partial"` |
| `scenarios` 비어 있음 | 입력 없음 | `status: "failed"`, `generate-scenarios` 실행 안내 |
| `BUILD_TOOL_UNDETECTED` | buildTool auto-detect 실패 | `warnings` 기록 후 기본 Gradle 가정으로 진행 |
| subagent 오류 | Task 호출 실패 | `status: "failed"`, `errors`에 원인 기록 |

보안: 파일 쓰기(Write/Edit) 외 실행(Bash) 권한 없음. 생성 코드에 실제 네트워크/Thread.sleep/broad catch 포함 금지.
