# Spring 테스트 하네스 플러그인

Claude Code CLI 기반 Spring 테스트코드 자동 생성 플러그인.
스펙 문서·AST 분석·시나리오 설계·코드 생성·실행·보정을 하나의 파이프라인으로 연결한다.

> **버전 인식(Spring Boot 2.0 – 4.x):** 대상 프로젝트의 Boot 버전 프로파일을 감지(`detect_spring_profile`)하여
> 네임스페이스(`javax`/`jakarta`), JUnit 엔진(JUnit4/Jupiter), Mock 애노테이션(`@MockBean`/`@MockitoBean`)을
> **자동 분기**해 컴파일 가능한 테스트를 생성한다. 매트릭스: [RESEARCH_NOTES §8](./RESEARCH_NOTES.md),
> 전체 템플릿: [references/version-compatibility.md](./references/version-compatibility.md).

> **독립 실행(OMC 비의존):** 이 플러그인은 `oh-my-claudecode`나 다른 외부 플러그인에 의존하지 않는다.
> Claude Code 네이티브 기능(플러그인 시스템·`Task` 서브에이전트·`AskUserQuestion`·MCP·훅)과 표준 툴체인
> (Python 3.10+, 선택적 JDK/Maven)만으로 동작한다. 상세: [DEPENDENCIES.md](./DEPENDENCIES.md).
> 모델도 `inherit`라 opus 없이 어떤 모델 환경에서도 실행된다.

---

## 설치

Claude Code 공식 plugin 구조로 배포된다. 플러그인 루트를 `.claude/plugins/` 아래에 복사하거나
심볼릭 링크를 생성한 뒤 Claude Code를 재시작하면 자동 인식된다.

```bash
# 예시: 저장소 루트에서 설치
cp -r spring-test-harness-plugin ~/.claude/plugins/spring-test-harness-plugin
# 또는 symlink
ln -s "$(pwd)/spring-test-harness-plugin" ~/.claude/plugins/spring-test-harness-plugin
```

설치 후 Claude Code 세션에서 `/spring-test-harness:full-pipeline` 명령이 인식되면 정상이다.

---

## 빠른 시작

```
/spring-test-harness:full-pipeline
```

명령 하나로 다음 파이프라인을 순서대로 실행한다.

1. 스펙 문서 인덱싱 (`ingest-specs`)
2. AST 구조 추출 (`analyze-ast`) — 스텝 1과 병렬
3. 소스 동작·seam 분석 (`analyze-source`)
4. 시나리오 설계 (`generate-scenarios`)
5. 테스트 코드 생성 (`generate-tests`)
6. 테스트 실행 (`run-tests`)
7. 실패 보정 (`repair-tests`) — 실패가 있을 때만

결과는 Markdown 보고서 + JSON 산출물로 저장된다.

---

## Skills (11종)

> v0.2 추가: `configure-harness`, `measure-coverage`, `mutation-test` (아래 "v0.2 신규" 절 참조)


| Skill | 호출 방법 | 역할 |
|---|---|---|
| `full-pipeline` | `/spring-test-harness:full-pipeline` | 전체 파이프라인 오케스트레이션 |
| `ingest-specs` | `/spring-test-harness:ingest-specs` | 스펙 문서 인덱싱·acceptance criteria 정규화 |
| `analyze-ast` | `/spring-test-harness:analyze-ast` | JavaParser 기반 AST 구조 추출 |
| `analyze-source` | `/spring-test-harness:analyze-source` | 동작·외부 I/O·mocking seam 분석 |
| `generate-scenarios` | `/spring-test-harness:generate-scenarios` | unit/slice/integration 시나리오 설계 |
| `generate-tests` | `/spring-test-harness:generate-tests` | JUnit Jupiter + Spring Test 코드 생성 |
| `run-tests` | `/spring-test-harness:run-tests` | 빌드 도구 감지 후 최소 범위 테스트 실행 |
| `repair-tests` | `/spring-test-harness:repair-tests` | 실패 원인 분류 후 최소 diff 보정 |

---

## Agents (9종)

> v0.2 추가: `coverage-closer`, `mutation-analyst`


| Agent | 역할 | 권한 |
|---|---|---|
| `ast-structure-analyzer` | AST/심볼 구조 추출 (read-only) | Read, Grep, Glob, MCP(repo-ast) |
| `source-code-analyzer` | 동작·seam 분석 (read-only) | Read, Grep, Glob, MCP(repo-ast, lsp) |
| `spec-reviewer` | 스펙 문서 인덱싱·criteria 정규화 (read-only) | Read, Grep, Glob, MCP(spec-doc) |
| `scenario-generator` | 시나리오 설계 (read-only) | Read, MCP(spec-doc, repo-ast) |
| `test-code-generator` | 테스트 파일 생성 (write) | Read, Write, Edit, MCP(repo-ast, build-test) |
| `test-runner` | 테스트 실행·XML 파싱 (execute) | Read, Bash, MCP(build-test) |
| `test-fixer` | 실패 보정 (write+execute) | Read, Write, Edit, Bash, MCP(all) |

plugin-shipped subagent는 `hooks`/`mcpServers`/`permissionMode` frontmatter를 선언할 수
없다(Claude Code 공식 제약). MCP 접근은 공유 `.mcp.json` + skill 라우팅으로 구현한다.

---

## MCP 서버 (3종, Python FastMCP)

공식 MCP Python SDK(FastMCP) 기반 stdio 서버. 구현체는 `mcp/`에 있다.

| MCP 서버 | 구현 | 주요 도구 |
|---|---|---|
| `repo-ast` | `mcp/repo_ast_server.py` (+ JavaParser jar) | `parse_java_file`, `resolve_symbol`, `list_spring_components`, `extract_test_targets`. 코드 본문 미반환 |
| `spec-doc` | `mcp/spec_doc_server.py` | `index_docs`, `search_requirements`, `extract_acceptance_criteria`. 경로 allowlist + redaction |
| `build-test` | `mcp/build_test_server.py` | `detect_build_tool`, `run_targeted_tests`, `parse_junit_xml`, `parse_jacoco_report`, `parse_pitest_report`, `coverage_gate` |

MCP 연결은 `.mcp.json`(Python으로 연결), 선택적 LSP(JDT LS)는 `.lsp.json` 참조.

### MCP 서버 설치

```bash
# 1) Python 의존성 (Python 3.10+)
pip install -r mcp/requirements.txt        # mcp[cli]

# 2) (선택, 권장) JavaParser AST 백엔드 빌드 — 없으면 정규식 fallback
cd mcp/javaparser-cli && mvn -q -DskipTests package
export REPO_AST_JAVAPARSER_JAR="$(pwd)/target/astcli-1.0.0-shaded.jar"
```

---

## v0.2 신규: near-100% 커버리지 · 뮤테이션 · 인터랙티브 설정

- **인터랙티브 설정(`configure-harness`)**: 파이프라인 시작 시 AskUserQuestion으로 4항목을 질문해
  도메인 특화 `HarnessConfig`를 구성한다 — ① 스펙 문서 경로 추가, ② 테스트 대상 폴더/패키지 선별,
  ③ 뮤테이션 깊이·대상, ④ 커버리지 임계값·제외 규칙. 비대화형(`claude -p`/CI)에서는 기본값으로 스킵.
- **커버리지 게이트(`measure-coverage` + `coverage-closer`)**: JaCoCo로 LINE/BRANCH/METHOD/CLASS를
  측정하고 near-100% 미달 시 추가 테스트를 생성·재측정하는 루프(기본 LINE≥0.95 / BRANCH≥0.90 /
  METHOD≥0.95 / CLASS=1.00, 제외 allowlist 적용).
- **뮤테이션 강화(`mutation-test` + `mutation-analyst`)**: PITest로 살아남은 mutant를 찾아 단언을
  강화(기본 mutation score ≥ 0.80). sleep/over-mock/broad-catch 금지.

기준 버전·API는 [RESEARCH_NOTES.md](./RESEARCH_NOTES.md) 참조.

---

## 테스트 생성 컨벤션 (BDD)

- **시나리오 = BDD 구조**: 각 시나리오는 `given`(전제·입력 배열) / `when`(검증 대상 단일 행위) /
  `then`(기대 결과·단언 배열)로 구조화된다. 스펙의 acceptance criteria(Given/When/Then 정규화)에서 파생.
- **메서드명에 scenarioRef 포함**: 테스트 메서드는 `<scenarioRefSlug>_<행위>` 형식(`SC-001` → `sc001_...`).
- **본문 3단 구조**: `// given` → `// when`(단일 행위, 결과 캡처) → `// then`(단언). 예외 검증은
  `// when & then` 병합 허용. 협력 stub은 BDDMockito `given().willReturn()/willThrow()`.
- **설명**: jupiter 프로파일은 `@DisplayName`(한국어 행위 서술), junit4 프로파일은 서술적 메서드명으로 대체.
- TDD(red-green) 워크플로는 제공하지 않으며, 기존 코드 대상 spec 기반 사후 생성 + BDD 표현에 집중한다.

## 보안 기본값

- **네트워크**: 기본 차단. 명시적으로 허용한 도메인만 접근 가능.
- **경로 allowlist**: 프로젝트 루트 외부 파일 참조 금지. generated/vendor/build output read deny.
- **민감정보 redaction**: `scripts/redact-secrets.py`로 토큰·비밀번호·접속문자열 마스킹.
- **hooks**: 사용자 권한·비샌드박스 실행이므로 보수적(알림 위주). `hooks/hooks.json` 참조.
- **쉘 인자 escaping**: build-test-mcp 및 run-tests.sh에서 강제.
- **CI secrets**: GitHub Actions Secrets에만 저장. 로그 출력 금지.
- **secret scanning**: GitHub 저장소 기능(Settings > Security > Secret scanning)으로 운영.
  이 플러그인의 CI 워크플로에는 포함하지 않는다.

---

## 버전 호환성

> **모델:** 모든 에이전트와 `Task` 호출은 `model: inherit`로 선언되어 **현재 세션 모델**을 그대로 사용한다.
> opus 전용이 아니므로 sonnet·haiku 등 어떤 모델 환경에서도 동작한다. 특정 티어를 강제하려면 해당
> `agents/*.md`의 `model:` 또는 스킬의 `Task(model="...")`를 명시 pin한다.

> **대상 Spring Boot 범위:** **2.0 – 4.x** (버전 프로파일 자동 분기). 아래 "권장/최소"는 latest(4.x) 프로파일 기준이며,
> Boot 2.x/3.x 대상은 프로파일에 맞춰 Java 8/17·`javax`/`jakarta`·JUnit4/5·`@MockBean`/`@MockitoBean`가 적용된다.
> 버전별 상세 매트릭스는 [RESEARCH_NOTES §8](./RESEARCH_NOTES.md), 빌드 예제는 `examples/`(`build-boot2.gradle`, `pom-snippet-boot2.xml`).

| 항목 | 권장(latest) | 지원 범위 | 비고 |
|---|---|---|---|
| Claude Code 모델 | inherit(현재 세션) | — | opus 불필요 |
| Spring Boot | 4.1.0 | **2.0 – 4.x** | 버전 프로파일 자동 감지/분기 |
| Spring Framework | 7.0.8+ | 5.0 – 7.x | Boot 버전에 종속 |
| Java | 17 | **8**(Boot 2.x) – 26 | 프로파일 `javaBaseline` |
| 네임스페이스 | `jakarta` | `javax`(Boot 2.x) / `jakarta`(3.x+) | 자동 분기 |
| JUnit | Jupiter/Platform 6.0.x | **JUnit 4**(Boot 2.0–2.1) / Jupiter | 자동 분기 |
| Mock 애노테이션 | `@MockitoBean` | `@MockBean`(≤3.3) / `@MockitoBean`(3.4+) | 자동 분기 |
| Gradle | 9.6 | 5.x – 9.x | 9.x 권장 |
| Maven | 최신 3.9.x+ | 3.6.3+ | |
| Mockito (BOM) | 5.2x | 2.x – 5.x | BOM 위임 |
| JDT LS (선택) | 최신 | Java 21+ runtime | `.lsp.json`으로 연결 |
| JaCoCo | 0.8.12 | — | line/branch/method/class 게이트 |
| PITest (Gradle) | gradle-pitest 1.19.0 | — | `junit5PluginVersion 1.0.0` |
| JavaParser | symbol-solver 3.28.2 | — | `mcp/javaparser-cli` |
| MCP Python SDK | `mcp[cli]` | Python 3.10+ | FastMCP, stdio |

JUnit 버전 정책 상세(`jupiter-style` vs `strict-5x`)는 [CHANGELOG.md](./CHANGELOG.md)의 "JUnit 버전 정책 — BOM 기본값과의 편차 명시" 절 참조.

---

## 예제 파일

| 파일 | 설명 |
|---|---|
| `examples/java/OrderControllerTest.java` | (Boot 4.x/3.4+) `@WebMvcTest` + `MockMvc` + `@MockitoBean` 슬라이스 |
| `examples/java/OrderControllerTest_boot2_jupiter.java` | (Boot 2.2–2.7) `@WebMvcTest` + `@MockBean` + Jupiter |
| `examples/java/OrderControllerTest_boot2_junit4.java` | (Boot 2.0–2.1) `@RunWith(SpringRunner.class)` + `@MockBean` + JUnit 4 |
| `examples/java/OrderAmountCalculatorTest.java` | 순수 단위 테스트 + `@ParameterizedTest` `@CsvSource` |
| `examples/json/scenario-example.json` | ScenarioSet JSON 스키마 예시 |
| `examples/json/test-run-result.json` | TestRunResult JSON (실패 포함) |
| `examples/json/repair-example.md` | 실패→최소 diff 보정 서술 |
| `examples/gradle/build.gradle.kts` | (Boot 4.x) Gradle 9.x 빌드 설정 |
| `examples/gradle/build-boot2.gradle` | (Boot 2.x) Groovy DSL, Java 8/11, JaCoCo/PITest + JUnit4 폴백 주석 |
| `examples/maven/pom-snippet.xml` | (Boot 4.x) Maven Surefire/Compiler 설정 스니펫 |
| `examples/maven/pom-snippet-boot2.xml` | (Boot 2.x) Java 8 parent + JaCoCo/PITest + JUnit4 폴백 주석 |
| `examples/ci/gradle-ci.yml` | GitHub Actions (Gradle) |
| `examples/ci/maven-ci.yml` | GitHub Actions (Maven) |

---

자세한 설계 근거·아키텍처·에이전트별 스키마는 설계 보고서(`REPORT.md`)에 정리되어 있으며,
이 보고서와 원칙 감사(`PRINCIPLES_AUDIT.md`)·검증 기록(`VERIFICATION.md`)은 플러그인 배포물과 분리하여
프로젝트의 `result_report/`에 보관한다. 핀 고정된 버전·API는 [RESEARCH_NOTES.md](./RESEARCH_NOTES.md)를 참조한다.
