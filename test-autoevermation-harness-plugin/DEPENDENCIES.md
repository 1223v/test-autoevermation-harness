# 런타임 의존성 — OMC 비의존 선언

본 플러그인은 **oh-my-claudecode(OMC)에 의존하지 않는다.** 빌드 과정에서 OMC 도구를 사용했더라도, 배포되는 산출물은 **Claude Code 네이티브 기능 + 표준 툴체인**만으로 동작한다.

## 의존하는 것 (모두 네이티브/표준)

| 범주 | 사용 기능 | 비고 |
|---|---|---|
| Claude Code 플러그인 시스템 | `.claude-plugin/plugin.json`, `skills/`, `agents/`, `hooks/`, `.mcp.json`, `.lsp.json` | 네이티브 |
| 서브에이전트 오케스트레이션 | `Task(subagent_type="<agent-name>")` 병렬/순차 호출 | 네이티브 (OMC 아님) |
| 인터랙티브 설정 | `AskUserQuestion` | 네이티브 (`configure-harness`, `full-pipeline`) |
| MCP | 공식 MCP 프로토콜(stdio) — `repo-ast`/`spec-doc`/`build-test` 서버 | 공식 표준 |
| 훅 | `PreToolUse`/`PostToolUse` (네트워크 가드, 시크릿 redaction) | 네이티브 |
| Python | 3.10+, `mcp[cli]` (MCP 서버 런타임) | 표준 |
| Java(권장) | JDK 17+ / Maven 3.6.3+ (JavaParser jar 빌드 — 정밀 AST). 미가용 시 **정규식 fallback으로 degrade**(`degraded:true`+경고). `REPO_AST_REQUIRE_JAVAPARSER=1`로 하드실패 강제는 opt-in. Phase E·E6에서 best-effort 빌드 | 권장 |
| JDT LS(선택) | `jdtls` + Java 21+ 런타임 (semantic 분석 보강). `plugin.json` `lspServers`로 `.lsp.json` 등록(미설치 시 graceful — AST-only degrade). Phase E·E7(선택) | 선택 |
| 대상 빌드 도구 | Gradle 8.14+/9.x 또는 Maven 3.6.3+ (대상 Spring 프로젝트용) | 대상 프로젝트 |

## 의존하지 않는 것 (명시적 비의존)

- ❌ `oh-my-claudecode` 플러그인 / 설치
- ❌ OMC 에이전트 (`executor`, `explore`, `planner` 등)
- ❌ OMC 스킬 (`ultrawork`, `ralph`, `autopilot`, `team` 등)
- ❌ OMC MCP 도구 (`mcp__plugin_oh-my-claudecode_t__*`)
- ❌ OMC 상태 관리 / `.omc/` 디렉터리
- ❌ 에이전트 팀 도구 (`TeamCreate`, `SendMessage`, `TaskCreate`) — 본 하네스는 **네이티브 서브에이전트**만 사용

> 검증: `grep -rinE 'oh-my-claudecode|mcp__plugin_oh-my-claudecode|TeamCreate|SendMessage' .` (`.omc/` 제외) → 0건. 모든 `subagent_type`은 본 플러그인 `agents/*.md`의 `name:` 필드와 1:1로 매칭된다.

## OMC가 제공하던 기능을 어떻게 자체 구현했나

빌드 단계에서 OMC가 편의로 제공하던 기능들은, 플러그인 런타임에는 아래처럼 **자체 구현/네이티브 대체**되어 있다.

| OMC 편의 기능 | 본 플러그인의 자체 구현 |
|---|---|
| 병렬 실행 엔진(ultrawork) | `full-pipeline`이 네이티브 `Task` 서브에이전트를 **직접** 팬아웃/파이프라인으로 오케스트레이션 (`references/orchestration-detail.md` §1) |
| 상태/체크포인트 | `_workspace/{단계}_{에이전트}_{산출물}.json` 파일 기반 전달 + Phase 0 부분 재실행 (자체 규약) |
| 작업 추적/타이밍 | `scripts/record-timing.py`로 `timing.json`(total_tokens/duration_ms) 자체 누적 |
| 인터뷰/질문 | 네이티브 `AskUserQuestion` (`configure-harness`) |
| 검증 루프 | 생성-검증 패턴을 스킬 본문에 자체 기술(coverage/mutation/repair 루프, 최대 반복 한도) |

## 설치 (OMC 불필요)

```bash
# 1) 플러그인을 Claude Code에 등록 (marketplace 또는 로컬 경로)
# 2) MCP 서버 런타임 — 전자동(v0.13.0+): 첫 세션에서 mcp/run-server.sh가
#    Python 3.10+가 없으면 uv(무-sudo)로 자동 설치하고, mcp/bootstrap.py가
#    ${CLAUDE_PLUGIN_DATA}/venv에 mcp[cli]를 설치 (수동 명령 불필요, macOS/Linux)
# 3) (선택) 정확한 Java AST
cd mcp/javaparser-cli && mvn -q -DskipTests package
```

OMC를 설치하지 않은 순정 Claude Code 환경에서 그대로 동작한다.
