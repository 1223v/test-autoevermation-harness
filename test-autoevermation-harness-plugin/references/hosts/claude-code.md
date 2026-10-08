# Claude Code 어댑터

기존 `.claude-plugin/plugin.json`, `.mcp.json`, `.lsp.json`, `hooks/hooks.json`, 역할 frontmatter 및 스킬 본문의 Claude 호출 형식을 유지한다. `Agent` 위임, 메인 대화의 `AskUserQuestion`/SDK 입력 호스트, 공식 LSP 조회, 훅의 순서·spawn 마커 검증을 그대로 수행한다.

- E1~E10 및 E-verify는 [environment-setup.md](../environment-setup.md)의 기존 항목을 적용한다. JDT LS의 Java 21+ 런타임과 실제 documentSymbol 연결 증거가 필요하다. `lspAvailable:true`를 설치 여부만으로 채우지 않는다.
- 플러그인 경로는 `CLAUDE_PLUGIN_ROOT`, 영속 데이터는 `CLAUDE_PLUGIN_DATA`, 대상은 `CLAUDE_PROJECT_DIR`/확정된 `projectRoot`를 사용한다. 기존 MCP 호출에서 `root`를 생략할 수 있다. 명시하면 기존 환경변수의 경계를 넓힐 수 없다.
- 상태줄 consent와 `/reload-plugins` 경로, `.claude/skills`에 저장하는 사용자 요청 프로젝트 스킬은 기존 절차를 유지한다.
- 질문 도구 부재만으로 자동 승인하지 않는다. 명시적 `skipInterview` 또는 호스트가 알린 입력 불가 모드에서만 기존 비대화형 정책을 적용한다. 필수 값이 없으면 중단한다.
- 공통 조사·실행 정책은 [evidence-workflow.md](../evidence-workflow.md)를 함께 적용한다. 이미 승인한 결정을 재승인시키거나 추가 메타 테스트 단계를 만들지 않는다.
