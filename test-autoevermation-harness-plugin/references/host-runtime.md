# 호스트 실행 계약

모든 스킬과 역할은 실행 전에 이 문서와 현재 호스트 문서를 읽는다. 설치 폴더명이나 질문 도구 부재로 호스트를 추정하지 않는다. 현재 세션의 호스트 정보와 실제 제공된 도구를 기준으로 선택한다. 불명확하면 메인 대화에서 확인한다.

- **Codex 앱·CLI**: [hosts/codex.md](hosts/codex.md). `HARNESS_HOST=codex`는 MCP 프로세스에 주입된다. 메인 셸에 이 변수가 없어도 Codex 세션은 Codex 규칙을 사용한다.
- **Claude Code**: [hosts/claude-code.md](hosts/claude-code.md).
- 두 호스트 공통: [evidence-workflow.md](evidence-workflow.md).

스킬 본문의 입력·출력 스키마, 단계 순서, 승인, 검증·반복 종료 규칙은 공용이다. `Agent(...)`, `AskUserQuestion`, LSP, `${CLAUDE_PLUGIN_*}`, `/reload-plugins`, `.claude/`, `.markers/` 및 훅 강제에 관한 실행 예시는 **Claude Code 어댑터**다. Codex는 해당 호출·필수 조건을 아래 대응표와 Codex 문서로 치환한다. Claude의 도구 이름을 Codex에서 호출하거나 LSP·위임 성공을 꾸며내지 않는다.

| 항목 | Claude Code | Codex 앱·CLI |
|---|---|---|
| 역할 실행 | 본문 `Agent` 호출 및 훅 계약 | `agents/*.md`를 읽어 인라인 실행; 스펙·AST만 선택적 독립 위임 |
| 사용자 질문 | `AskUserQuestion`, SDK 입력 호스트 | 실제 노출된 질문 도구; 없으면 일반 대화로 질문 후 응답 대기 |
| 파일·셸·검색 | Read/Grep/Glob/Write/Edit/Bash/WebSearch/WebFetch | 실제 파일·셸·웹 도구로 동일 목적 수행 |
| MCP 이름 | 본문 namespaced 예시 | 도구 목록에서 서버·메서드 확인 후 실제 이름 사용 |
| MCP 프로젝트 경로 | 기존 환경변수와 cwd; optional `root` | 확정된 절대 `projectRoot`를 모든 프로젝트 접근 호출의 `root`로 전달 |
| 분석 | JavaParser + 실제 JDT LS | JavaParser + 소스·빌드 근거; `lspAvailable:false` |
| 설치/영속 경로 | `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA` | `PLUGIN_ROOT` / `PLUGIN_DATA` (프로젝트 루트와 별개) |
| 승인·순서 강제 | 기존 훅·spawn 마커 | 스킬 지침; 훅/가짜 마커 없음 |
| 상태줄 | 선택 설치 | 적용하지 않음 |

호스트가 바뀌어도 테스트 생성 승인은 새로 만들어내지 않는다. 기존 승인과 재개 증거가 현재 대상·시나리오·소스에 유효한지 확인한다. 스킬의 도구 가용성 차이는 비대화형 실행이나 승인에 대한 근거가 아니다.
