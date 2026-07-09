# Spring 테스트 하네스 플러그인

Claude Code CLI 기반 Spring 테스트코드 자동 생성 플러그인.
스펙 문서·AST 분석·시나리오 설계·코드 생성·실행·보정을 하나의 파이프라인으로 연결한다.

> **상세 가이드**: 동작 원리·설치·사용법·설정·트러블슈팅을 한 곳에 정리한 종합 가이드는
> [docs/GUIDE.md](./docs/GUIDE.md) 참조.

> **버전 인식(Spring Boot 2.0 – 4.x):** 대상 프로젝트의 Boot 버전 프로파일을 감지(`detect_spring_profile`)하여
> 네임스페이스(`javax`/`jakarta`), JUnit 엔진(JUnit4/Jupiter), Mock 애노테이션(`@MockBean`/`@MockitoBean`)을
> **자동 분기**해 컴파일 가능한 테스트를 생성한다. 매트릭스: [RESEARCH_NOTES §8](./RESEARCH_NOTES.md),
> 전체 템플릿: [references/version-compatibility.md](./references/version-compatibility.md).

> **독립 실행(OMC 비의존):** 이 플러그인은 `oh-my-claudecode`나 다른 외부 플러그인에 의존하지 않는다.
> Claude Code 네이티브 기능(플러그인 시스템·`Task` 서브에이전트·`AskUserQuestion`·MCP·훅)과 표준 툴체인
> (Python 3.10+, JDK 21+, Maven은 선택 — `mvnw` 동봉)만으로 동작한다. 상세: [DEPENDENCIES.md](./DEPENDENCIES.md).
> 모델도 `inherit`라 opus 없이 어떤 모델 환경에서도 실행된다.

---

## 설치

### 0) 사전 요구사항

v0.16.0부터 **MCP 3종 연결 검증(E3b)·JavaParser AST 백엔드·JDT LS가 모두 필수**다(Breaking —
"아무것도 미리 설치할 필요 없다"는 v0.13.0~v0.15.x 한정 서술이며 더 이상 유효하지 않다):

- **Python**: PATH에 3.10+가 없으면 첫 세션에서 [uv](https://docs.astral.sh/uv/)로 관리형
  Python을 자동 설치한다(공식 standalone installer, **sudo 불필요**, 사용자 홈 `~/.local` —
  시스템 비오염). 비활성화: `HARNESS_AUTO_PYTHON=0`.
- **`mcp` 패키지**: 첫 세션에서 `mcp/bootstrap.py`가 플러그인 전용 venv
  (`${CLAUDE_PLUGIN_DATA}/venv`)에 자동 설치한다(v0.12.0+).

| 요구사항 | 확인 | 비고 |
|---|---|---|
| Node.js (Claude Code 실행 환경) | `node --version` | MCP·훅 진입점(`mcp/launch.cjs`)이 node로 실행된다 — 공식 훅 문서의 크로스플랫폼 패턴("node + 스크립트 경로는 전 플랫폼 동작"). npm 설치형 Claude Code에는 이미 존재 |
| **JDK 21+ (필수)** | `java -version` | JavaParser jar 빌드(17+)와 JDT LS 구동(21+)을 아우르는 단일 기준. 미탐지 시 Phase E(E4/E7)가 remediation과 함께 하드 중단한다. 상세: [DEPENDENCIES.md](./DEPENDENCIES.md) |
| Maven (선택 — `mvnw` 동봉) | — | 시스템 Maven 불필요 — `mcp/javaparser-cli`에 Maven Wrapper가 동봉되어 `./mvnw -q -DskipTests package`로 자동 빌드된다 |
| Python 3.10+ (자동 — **전 OS**: macOS/Linux/WSL/Windows) | `python3 --version` (Windows: `py -3 --version`) | 없으면 uv로 자동 설치(v0.15.0+, POSIX `install.sh` / Windows `install.ps1`). Windows 네이티브 지원 — 빌드 래퍼는 `gradlew.bat`/`mvnw.cmd` 자동 인식 |
| 네트워크 (최초 1회) | — | Maven 의존성·`mvnw` 배포판·JDT LS tarball 다운로드에 필요. 오프라인 환경은 `REPO_AST_JAVAPARSER_JAR` 사전 지정 + jdtls 사전 설치로 대체 |

### 1) 마켓플레이스 설치 (권장)

Claude Code 세션에서:

```text
/plugin marketplace add 1223v/test-autoevermation-harness
/plugin install test-autoevermation-harness-plugin@test-autoevermation-harness
/reload-plugins
```

### 2) 로컬 설치 (대안)

플러그인 루트를 `.claude/plugins/` 아래에 복사하거나 심볼릭 링크를 생성한 뒤 Claude Code를
재시작하면 자동 인식된다.

```bash
# 예시: 저장소 루트에서 설치
cp -r test-autoevermation-harness-plugin ~/.claude/plugins/test-autoevermation-harness-plugin
# 또는 symlink
ln -s "$(pwd)/test-autoevermation-harness-plugin" ~/.claude/plugins/test-autoevermation-harness-plugin
```

> `.gitignore` 항목(`.omc/`, `mcp/__pycache__/`, `mcp/javaparser-cli/target/` 등)은 배포에 불필요하다 —
> 빌드/런타임 산출물이므로 복사하지 않아도 되고, JavaParser jar는 Phase E(E6)가 동봉된 `mvnw`로
> `./mvnw -q -DskipTests package` 자동 빌드한다(v0.16.0부터 필수 — 실패 시 `JAVAPARSER_REQUIRED`로 하드 중단).

### 3) 설치 확인

- 세션에서 `/test-autoevermation-harness-plugin:full-pipeline` 명령이 자동완성에 뜨면 정상.
- **자동 설치가 실패하면 세션 시작 화면에 수동 폴백 명령이 그대로 표시된다**(v0.13.1+ —
  SessionStart 훅이 exit 2 + stderr로 안내; 세션은 정상 진행). 표시된 명령(Python 설치 →
  `python3 -m pip install -r mcp/requirements.txt`) 실행 후 `/reload-plugins` 하면 된다.
- `/plugin` Errors 탭에 MCP 서버 3종(repo-ast·spec-doc·build-test) 에러가 보이면:
  첫 세션은 Python/의존성 자동 설치 중일 수 있으니 잠시 후 `/reload-plugins`.
  계속 실패하면 MCP 로그(`mcp-logs-plugin-*`)의 `run-server`/`bootstrap` 진단을 확인한다.
- **Phase E의 `E3b`가 파이프라인 실행 전 `health` 도구 3종을 실제로 호출해 연결을 검증한다**(v0.16.0+) —
  실패 시 대화형/CI 모두 remediation과 함께 하드 중단하며, silent degrade로 계속 진행하지 않는다.
- `jdtls`는 v0.16.0부터 **필수**다 — 감지 실패 시 `scripts/setup_jdtls.py`가 자동 설치를 시도하고,
  그래도 실패하면 (E7) 하드 중단한다.

### 상태줄 진행률 표시 (자동)

플러그인 버전·파이프라인 진행률·현재 단계가 Claude Code 상태줄 하단에 표시된다(기존 상태줄
출력은 그대로 유지):

```text
[Test-AutoEverMation#<version>] 43% | stage 4: generate-scenarios
[Test-AutoEverMation#<version>] 79% | ↩ resumed @ stage 8: measure-coverage
```

- **상태 복원 재개(v0.20.0+)**: **하네스가 생성한** 테스트가 있는 프로젝트에서 `_workspace/`가 휘발(fresh
  clone·checkout·새 세션)해도, full-pipeline이 `detect_pipeline_state`로 영속 증거를 판정해 알맞은 단계부터
  재개하고 상태줄은 `↩ resumed @ <단계>`로 표시한다(전체 재실행 회피). **기존에 손으로 짠 테스트만** 있고
  하네스 흔적(`test_docs/`)이 없으면 이를 "생성 완료"로 오인하지 않고 정식으로 시나리오 설계·테스트 생성을
  진행하되, 기존 테스트는 덮어쓰지 않고 커버리지 갭만 보완한다(v0.20.1+).
- **자동 설치**: 설치 후 첫 세션에서 "상태줄을 설치할까요?"를 **한 번** 물은 뒤, 승인하면
  이후 세션부터 자동으로 유지된다(모든 세션에 표시; 파이프라인 없는 프로젝트에선 버전만).
  기존 상태줄(예: OMC HUD)은 delegate로 보존되어 계속 실행되고, 다른 도구가 상태줄을
  되가져가도 다음 세션 시작에 자동으로 재점유한다.
- **자동 제거**: 플러그인을 uninstall하면, 재시작 후 첫 상태줄 렌더에서 원래 상태줄로 자동
  원복된다(Claude Code에 uninstall 훅이 없어 전역 사본이 스스로 정리하는 방식).
- **끄기**: 자동 설치를 원치 않으면 최초 확인에서 "설치 안 함"을 고르거나, 환경변수
  `TAM_STATUSLINE_AUTO=0`으로 비활성화한다. 이미 설치했다면
  `/test-autoevermation-harness-plugin:setup-statusline`에 "제거"를 요청해 즉시 원복할 수 있다.

상세: [docs/GUIDE.md §5.5](./docs/GUIDE.md).

---

## 제거

```text
# 플러그인만 제거
/plugin uninstall test-autoevermation-harness-plugin@test-autoevermation-harness

# 마켓플레이스 등록까지 해제 — 이 마켓플레이스에서 설치한 플러그인도 함께 제거된다(공식 동작)
/plugin marketplace remove test-autoevermation-harness
```

- 제거하지 않고 잠시 끄려면 `/plugin disable test-autoevermation-harness-plugin@test-autoevermation-harness`,
  다시 켜려면 같은 인자로 `/plugin enable`.
- [로컬 설치](#2-로컬-설치-대안)를 사용한 경우에는 `~/.claude/plugins/test-autoevermation-harness-plugin`을
  삭제한 뒤 Claude Code를 재시작한다.
- 변경 사항은 `/reload-plugins` 또는 세션 재시작으로 반영된다.
- **상태줄은 자동 원복된다**: uninstall 후 Claude Code를 재시작하면 첫 상태줄 렌더에서 원래
  상태줄로 되돌아간다(전역 사본의 self-heal). 즉시 원복하려면 uninstall 전에
  `/test-autoevermation-harness-plugin:setup-statusline`에 "제거"를 요청한다.

---

## 재설정

**최신 버전 반영(일반 재설정):**

```text
/plugin marketplace update test-autoevermation-harness
/reload-plugins
```

**설치 상태가 깨졌을 때(스킬 미노출·MCP 서버 에러 지속):** 공식 트러블슈팅 절차대로 플러그인 캐시를
비우고 재설치한다.

```bash
rm -rf ~/.claude/plugins/cache
```

이후 Claude Code를 재시작하고 위 [설치](#설치) 절차를 다시 실행한다.

**하네스 실행 상태 재설정:** 파이프라인 중간 산출물은 대상 프로젝트 루트의 `_workspace/`에 저장된다
(부분 재실행용). 이 디렉터리를 삭제해도 **무조건 처음부터 다시 시작하지는 않는다** — 생성된 테스트·
승인 시나리오·커버리지/뮤테이션 리포트 같은 영속 증거가 남아 있으면 `detect_pipeline_state`가 이를
판정해 알맞은 단계부터 재개한다(위 "상태 복원 재개(v0.20.0+)" 참고). 영속 증거가 전혀 없는 프로젝트만
0단계(`configure-harness` 인터뷰 포함)부터 시작한다. 새 입력으로 다시 돌리면 기존 산출물은 자동으로
`_workspace_{timestamp}/`로 보존되므로 수동 삭제는 선택이다. `test_docs/`는 사람이 읽는 영속 산출물이므로
유지한다. 부분 재실행/재개 방법 상세는 docs/GUIDE.md 참고. 상태줄은 uninstall 시
자동 원복되며(위 [제거](#제거) 절), 즉시 끄려면 `/test-autoevermation-harness-plugin:setup-statusline`에
"제거"를 요청한다. 상세: [docs/GUIDE.md §4.5~4.6](./docs/GUIDE.md).

---

## 빠른 시작

```
/test-autoevermation-harness-plugin:full-pipeline
```

명령 하나로 다음 파이프라인을 순서대로 실행한다.

1. 스펙 문서 인덱싱 (`ingest-specs`)
2. AST 구조 추출 (`analyze-ast`) — 스텝 1과 병렬
3. 소스 동작·seam 분석 (`analyze-source`)
3.5. **리팩토링 권고 게이트 (`refactor-advisory`)** — 복잡도·비효율·테스트 저해 코드를 공식문서 근거로 판정, `test_docs/refactoring/RA-*.md` 권고 작성 후 대화형은 `AskUserQuestion`으로 생성 대상 포함/제외 결정(플래그 0건이면 자동 통과)
4. 시나리오 설계 (`generate-scenarios`)
4.5. **시나리오 승인 게이트 + `test_docs/` 저장** — 대화형은 `AskUserQuestion`으로 승인, 승인분만 진행
5. 테스트 코드 생성 (`generate-tests`)
6. 테스트 실행 (`run-tests`)
7. 실패 보정 (`repair-tests`) — 실패가 있을 때만
8. 커버리지 게이트 (`measure-coverage`)
9. 뮤테이션 강화 (`mutation-test`)
10. **시나리오 적합성 검증 (`verify-scenarios`)** — 통과한 테스트가 시나리오를 실제로 만족하는지 검증(target 호출은 `methodCalls` 기계 대조) 후 `test_docs/` 정리
10.5. **적합성 자동 보정 루프** — `unmet`(unsatisfied/missing)이 있으면 자동 보정: unsatisfied→`test-fixer` 모드 B(`SCENARIO_NONCONFORMANT`) / missing→부분 재생성 → 재실행·재검증. 최대 3라운드, 대화형·CI 동일

결과는 Markdown 보고서 + JSON 산출물 + 대상 프로젝트의 `test_docs/`(시나리오↔테스트코드↔결과 living documentation + `refactoring/` 리팩토링 권고)로 저장된다.

> **흐름도**: 전체 구동 흐름(Phase E·승인 게이트·적합성 검증·fallback 분기)을 Mermaid로 시각화한 문서는
> [docs/pipeline-flow.md](./docs/pipeline-flow.md) 참조.

---

## Skills (14종)

| Skill | 호출 방법 | 역할 |
|---|---|---|
| `configure-harness` | `/test-autoevermation-harness-plugin:configure-harness` | 환경 세팅(Phase E) + 인터랙티브 설정 → `HarnessConfig` 생성 |
| `full-pipeline` | `/test-autoevermation-harness-plugin:full-pipeline` | 전체 파이프라인 오케스트레이션 |
| `ingest-specs` | `/test-autoevermation-harness-plugin:ingest-specs` | 스펙 문서 인덱싱·acceptance criteria 정규화 |
| `analyze-ast` | `/test-autoevermation-harness-plugin:analyze-ast` | JavaParser 기반 AST 구조 추출 |
| `analyze-source` | `/test-autoevermation-harness-plugin:analyze-source` | 동작·외부 I/O·mocking seam 분석 |
| `refactor-advisory` | `/test-autoevermation-harness-plugin:refactor-advisory` | 복잡도·비효율·테스트 저해 코드 판정(3.5 게이트의 read-only 판정부) |
| `generate-scenarios` | `/test-autoevermation-harness-plugin:generate-scenarios` | unit/slice/integration 시나리오 설계 |
| `generate-tests` | `/test-autoevermation-harness-plugin:generate-tests` | JUnit Jupiter + Spring Test 코드 생성 |
| `run-tests` | `/test-autoevermation-harness-plugin:run-tests` | 빌드 도구 감지 후 최소 범위 테스트 실행 |
| `repair-tests` | `/test-autoevermation-harness-plugin:repair-tests` | 실패 원인 분류 후 최소 diff 보정 |
| `measure-coverage` | `/test-autoevermation-harness-plugin:measure-coverage` | JaCoCo near-100% 커버리지 게이트 루프 |
| `mutation-test` | `/test-autoevermation-harness-plugin:mutation-test` | PITest 뮤테이션 강화 루프 |
| `verify-scenarios` | `/test-autoevermation-harness-plugin:verify-scenarios` | 시나리오 적합성 검증 + `test_docs/` 정리 |
| `setup-statusline` | `/test-autoevermation-harness-plugin:setup-statusline` | Claude Code 상태줄에 플러그인 버전·진행률·현재 단계 표시(설치/제거) |

---

## Agents (11종)

| Agent | 역할 | 권한 |
|---|---|---|
| `ast-structure-analyzer` | AST/심볼 구조 추출 (read-only) | Read, Grep, Glob, MCP(repo-ast) |
| `source-code-analyzer` | 동작·seam 분석 (read-only) | Read, Grep, Glob, MCP(repo-ast, lsp) |
| `refactor-advisor` | 복잡도·비효율·테스트 저해 판정 (read-only) | Read, Grep, Glob, MCP(repo-ast, lsp) |
| `spec-reviewer` | 스펙 문서 인덱싱·criteria 정규화 (read-only) | Read, Grep, Glob, MCP(spec-doc) |
| `scenario-generator` | 시나리오 설계 (read-only) | Read, MCP(spec-doc, repo-ast) |
| `test-code-generator` | 테스트 파일 생성 (write) | Read, Write, Edit, MCP(repo-ast, build-test) |
| `test-runner` | 테스트 실행·XML 파싱 (execute) | Read, Bash, MCP(build-test) |
| `test-fixer` | 실패 보정 (write+execute) | Read, Write, Edit, Bash, MCP(all) |
| `coverage-closer` | 미커버 gap 보완 테스트 생성 (write, no Bash) | Read, Write, Edit, MCP(repo-ast, build-test) |
| `mutation-analyst` | 생존 mutant 제거 단언 강화 (write, no Bash) | Read, Write, Edit, MCP(repo-ast, build-test) |
| `scenario-conformance-verifier` | 시나리오 적합성 검증 + `test_docs/` 기록 (verify+write) | Read, Write, Edit, Grep, Glob, MCP(repo-ast, build-test) |

plugin-shipped subagent는 `hooks`/`mcpServers`/`permissionMode` frontmatter를 선언할 수
없다(Claude Code 공식 제약). MCP 접근은 공유 `.mcp.json` + skill 라우팅으로 구현한다.

---

## MCP 서버 (3종, Python FastMCP)

공식 MCP Python SDK(FastMCP) 기반 stdio 서버. 구현체는 `mcp/`에 있다.

| MCP 서버 | 구현 | 주요 도구 |
|---|---|---|
| `repo-ast` | `mcp/repo_ast_server.py` (+ JavaParser jar, 필수) | `parse_java_file`, `resolve_symbol`, `list_spring_components`, `extract_test_targets`, `health`. 코드 본문 미반환 |
| `spec-doc` | `mcp/spec_doc_server.py` | `index_docs`, `search_requirements`, `extract_acceptance_criteria`, `health`. 경로 allowlist + redaction |
| `build-test` | `mcp/build_test_server.py` | `detect_build_tool`, `detect_spring_profile`, `detect_build_capabilities`(v0.8), `check_dependency_cache`(v0.8), `list_test_tasks`, `run_targeted_tests`(`online=` 프라이밍), `parse_junit_xml`, `parse_jacoco_report`, `parse_pitest_report`, `coverage_gate`, `detect_pipeline_state`(v0.20 — 영속 증거 기반 상태 복원), `health` |

MCP 연결은 `.mcp.json`(Python으로 연결)이며, 파이프라인 시작 전 Phase E `E3b`가 `health` 3종을 실호출해
연결을 검증한다(실패 시 하드 중단). LSP(JDT LS)는 `plugin.json`의 `lspServers`로 `.lsp.json`을 등록하며
v0.16.0부터 **필수**다 — 미설치 시 `scripts/setup_jdtls.py`가 자동 설치를 시도하고, 그래도 실패하면 (E7) 하드 중단한다.

### MCP 서버 설치

> **v0.12.0부터 Python 의존성은 자동 설치된다**: 플러그인 설치 후 첫 세션에서
> `mcp/bootstrap.py`가 `${CLAUDE_PLUGIN_DATA}/venv`(업데이트에도 유지되는 공식 플러그인
> 데이터 디렉터리)에 `mcp[cli]`를 1회 설치하고, 이후 MCP 서버 3종은 그 venv로 실행된다.
> 수동 `pip install` 불필요. (시스템 python3에 이미 `mcp`가 있으면 venv 없이 그대로 사용)

```bash
# 1) Python 의존성 — 자동 (Python 3.10+만 있으면 됨). 수동 폴백이 필요할 때만:
python3 -m pip install -r mcp/requirements.txt        # mcp[cli]>=1.2.0

# 2) JavaParser AST 백엔드 빌드 (필수, v0.16.0+)  ── Phase E·E6
#    .mcp.json 기본값이 REPO_AST_REQUIRE_JAVAPARSER=1 — jar가 없으면 정규식 fallback 없이 하드실패한다.
#    시스템 Maven 불요 — mvnw(Maven Wrapper)가 mcp/javaparser-cli에 동봉되어 있다.
cd mcp/javaparser-cli && ./mvnw -q -DskipTests package    # JDK 21+
export REPO_AST_JAVAPARSER_JAR="$(pwd)/target/astcli-1.0.0-shaded.jar"   # 다른 위치를 쓸 때만 필요
```

---

## v0.2 신규: near-100% 커버리지 · 뮤테이션 · 인터랙티브 설정

- **환경 세팅 선행(`Phase E`)**: 인터뷰 전에 [environment-setup.md](references/environment-setup.md)
  체크리스트(MCP SDK·JavaParser jar·JDT LS·빌드도구·Spring 프로파일·테스트 실행 JDK)를 TODO로 **선세팅**한다 —
  대화형=항목별 함께 세팅, CI=결정적 항목 자동 세팅. 미충족이면 파이프라인을 시작하지 않는다.
- **인터랙티브 설정(`configure-harness`)**: 파이프라인 시작 시 AskUserQuestion으로 4항목을 질문해
  도메인 특화 `HarnessConfig`를 구성한다 — ① 스펙 문서 경로 추가, ② 테스트 대상 폴더/패키지 선별,
  ③ 뮤테이션 깊이·대상, ④ 커버리지 임계값·제외 규칙. 비대화형(`claude -p`/CI)에서는 `HarnessRequest` 값으로 진행.
- **커버리지 게이트(`measure-coverage` + `coverage-closer`)**: JaCoCo로 LINE/BRANCH/METHOD/CLASS를
  측정하고 near-100% 미달 시 추가 테스트를 생성·재측정하는 루프(기본 LINE≥0.95 / BRANCH≥0.90 /
  METHOD≥0.95 / CLASS=1.00, 제외 allowlist 적용).
- **뮤테이션 강화(`mutation-test` + `mutation-analyst`)**: PITest로 살아남은 mutant를 찾아 단언을
  강화(기본 mutation score ≥ 0.80). sleep/over-mock/broad-catch 금지.

기준 버전·API는 [RESEARCH_NOTES.md](./RESEARCH_NOTES.md) 참조.

---

## v0.8 신규: 대상 빌드 능력 프로비저닝 · 캐시 프라이밍

Phase E가 **하네스 런타임**만 세팅하던 공백을 메운다. 대부분의 실제 프로젝트는 JaCoCo **XML**(Gradle 기본 OFF)·
PITest 플러그인이 없어 커버리지(8단계)·뮤테이션(9단계)이 깨지고, 네트워크 기본 OFF(`--offline`)라 콜드 캐시
첫 실행(6단계)이 의존성 해석 실패로 깨질 수 있다. **0.6단계**에서 선제 처리한다(정본: [references/build-provisioning.md](./references/build-provisioning.md)).

- **빌드 능력(#17)**: `detect_build_capabilities`가 JaCoCo XML·PITest·pitest-junit5 유무를 감지 → 대화형은
  `AskUserQuestion` 승인 후 **최소 스니펫 주입**(`buildChanges[]` 기록), CI는 자동 주입 금지·remediation 중단. (`detect→approve→inject`)
- **캐시 프라이밍(#18)**: `check_dependency_cache`가 콜드 캐시를 신호 → 대화형은 승인 후 `run_targeted_tests(online=True)`
  **1회** 온라인 프라이밍(또는 Maven `dependency:go-offline`), 이후 오프라인 유지. 상시 온라인 아님(보안 기본값 유지).

> 근거(공식문서): [Gradle JaCoCo XML 기본 OFF](https://docs.gradle.org/current/userguide/jacoco_plugin.html),
> [gradle-pitest-plugin](https://gradle-pitest-plugin.solidsoft.info/),
> [Gradle `--offline` 미캐시 실패](https://docs.gradle.org/current/userguide/dependency_caching.html),
> [Maven `dependency:go-offline`](https://maven.apache.org/plugins/maven-dependency-plugin/go-offline-mojo.html).

---

## 테스트 생성 컨벤션 (BDD)

- **시나리오 = BDD 구조**: 각 시나리오는 `given`(전제·입력 배열) / `when`(검증 대상 단일 행위) /
  `then`(기대 결과·단언 배열)로 구조화된다. 스펙의 acceptance criteria(Given/When/Then 정규화)에서 파생.
- **메서드명에 scenarioRef 포함**: 테스트 메서드는 `<scenarioRefSlug>_<행위>` 형식(`SC-001` → `sc001_...`).
- **본문 3단 구조**: `// given` → `// when`(단일 행위, 결과 캡처) → `// then`(단언). 예외 검증은
  `// when & then` 병합 허용. 협력 stub은 BDDMockito `given().willReturn()/willThrow()`.
- **설명**: jupiter 프로파일은 `@DisplayName`(한국어 행위 서술), junit4 프로파일은 서술적 메서드명으로 대체.
- TDD(red-green) 워크플로는 제공하지 않으며, 기존 코드 대상 spec 기반 사후 생성 + BDD 표현에 집중한다.

## 시나리오 승인 · 적합성 검증 · `test_docs/` (v0.7)

시나리오는 **사용자 승인**을 받고, 모든 과정이 끝나면 **시나리오 충족 여부를 검증**한다. 결과는 대상 프로젝트의
`test_docs/`에 living documentation으로 정리된다. 정본: [references/scenario-docs.md](./references/scenario-docs.md).

- **승인 게이트(4.5단계)**: 시나리오 설계 직후, 테스트 생성 전에 `test_docs/scenarios/<id>.md`로 저장하고
  대화형은 `AskUserQuestion`(전체 승인 / 일부 제외·수정 / 재설계)으로 묻는다. **승인된 시나리오만** 생성으로 진행.
  비대화형·CI는 자동 승인 후 기록(승인은 본질적으로 대화형 전용). 제외분은 `excluded`로 보존.
- **적합성 검증(10단계)**: `verify-scenarios` + `scenario-conformance-verifier`가 `scenarioRef`(메서드명 `sc001_…` +
  javadoc)로 시나리오↔테스트를 매핑하고, 통과한 테스트가 시나리오 given/when/then을 **실제로 만족**하는지
  판정한다(satisfied/unsatisfied/missing). `// then` 단언이 시나리오 then을 빠짐없이 반영해야 satisfied.
  `unmet`이 있으면 파이프라인 `status: partial` + 잔여 전량 보고(임의 제외 금지).
- **산출물 구조**:

  ```
  <projectRoot>/test_docs/
  ├── INDEX.md                # 시나리오↔테스트코드↔결과 매핑 표 + 요약
  └── scenarios/
      ├── SC-001.md           # 시나리오 1건 = 파일 1개 (BDD + 매핑 + 검증 결과)
      └── ...
  ```

  `test_docs/`는 사람이 읽는 **영속 산출물**이라 대상 프로젝트에 커밋될 수 있다(`_workspace/` 중간 JSON과 분리).

> 설계 근거(BDD/Living Documentation 추적성, 웹 검증 2026-06-27): Serenity BDD Living Documentation,
> Cucumber "How does BDD affect traceability", JUnit 5 `@DisplayName` 리포팅 추적성.

## 보안 기본값

- **네트워크**: 기본 차단. 명시적으로 허용한 도메인만 접근 가능.
- **경로 allowlist**: 프로젝트 루트 외부 파일 참조 금지. generated/vendor/build output read deny.
- **민감정보 redaction**: `scripts/redact-secrets.py`로 토큰·비밀번호·접속문자열 마스킹.
- **hooks**: 사용자 권한·비샌드박스 실행이므로 보수적(알림 위주). `hooks/hooks.json` 참조.
- **쉘 인자 escaping**: build-test-mcp(`run_targeted_tests`)에서 shlex로 강제.
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
| JDT LS (필수, v0.16.0+) | 최신 | Java 21+ runtime | `plugin.json` `lspServers`→`.lsp.json`(node 경유 `mcp/jdtls-launcher.cjs`) 등록, 미설치 시 `scripts/setup_jdtls.py` 자동 설치·실패 시 하드 중단 |
| JaCoCo | 0.8.12 | — | line/branch/method/class 게이트 |
| PITest (Gradle) | gradle-pitest 1.19.0 | — | `junit5PluginVersion 1.0.0` |
| JavaParser | symbol-solver 3.28.2 | — | `mcp/javaparser-cli` |
| MCP Python SDK | `mcp[cli]` | Python 3.10+ | FastMCP, stdio |

JUnit 버전 정책 상세(`jupiter-style` vs `strict-5x`)는 [CHANGELOG.md](./CHANGELOG.md)의 "JUnit 버전 정책 — BOM 기본값과의 편차 명시" 절 참조.

---

## 커스텀 컴포넌트

직접 만든 Spring 컴포넌트도 인식한다(상세·근거: [references/custom-components.md](./references/custom-components.md)).

| 유형 | 분류 | 자동탐지 | 테스트 전략 |
|---|---|---|---|
| 커스텀 스테레오타입 `@UseCase`(`@Component` 메타) | component(또는 specialization) | 포함 | 순수 단위(Mockito + BDD) |
| 거리 2 전이 `@ReadModel → @UseCase → @Component` | component | 포함 | 순수 단위 |
| 합성 매핑 `@GetJson`(`@RequestMapping` 메타) 컨트롤러 | controller | 포함 | `@WebMvcTest`+MockMvc, **path/method 확인 후** |
| 커스텀 `ConstraintValidator`/`Converter` 등 | pojo | (kinds 미지정 시) 포함 | 순수 단위(계약 메서드) |

`repo-ast-mcp`가 `@interface` 메타 애노테이션을 **전이적으로** 해석한다. 합성 매핑 애노테이션은
URL path/HTTP method가 `@AliasFor`에 숨으므로 `riskPoints`로 표시되어 생성기가 경로를 확인한다.

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

동작 원리·아키텍처·사용법 종합 가이드는 [docs/GUIDE.md](./docs/GUIDE.md),
핀 고정된 버전·API는 [RESEARCH_NOTES.md](./RESEARCH_NOTES.md)를 참조한다.
