# 하네스 개발 규칙

이 저장소는 Spring 테스트 생성 도구다. Claude Code와 Codex 앱·CLI가 공용 스킬과 MCP 구현을 사용한다.

- 변경 전 관련 디렉터리, 매니페스트, 호출 경로, 입력·출력 계약과 영향받는 소스 파일을 읽는다. 저장소 전체를 추측으로 설명하지 않는다.
- 실제 의존성 버전을 확인하고 해당 버전의 공식 문서·공식 구현을 조사한다. 파일·심볼, URL, 확인 버전, 적용 결정을 조사 기록에 남긴 뒤 TODO를 세운다. 변경 없는 조사는 재사용한다.
- 실패는 재현·원인 확인 후 최소 범위로 고친다. 관련 검증 결과를 확인한 뒤 완료를 보고한다. 미실행 환경을 통과로 쓰지 않는다.
- 플러그인 자체 `tests/` 파일은 추가·수정·삭제하지 않는다. 기존 검사와 실제 MCP·빌드 실행을 재사용한다. 별도 메타 테스트, mutation testing, 의무 RED–GREEN TDD, 중복 리뷰·승인 단계를 추가하지 않는다.
- 생성 대상 프로젝트의 테스트 실행·보정·JaCoCo·시나리오 적합성 검증은 유지한다. 시나리오 승인과 기존 반복 종료 조건을 약화하지 않는다.
- Codex에 Claude의 LSP, 상태줄, 강제 위임 훅을 이식하지 않는다. 전역 에이전트 설정을 설치하지 않는다. 호스트별 규칙은 배포되는 `references/host-runtime.md`에서 연결한다.
- 스키마 v2와 기존 MCP 도구 이름·root 생략 시 Claude 동작을 유지한다. 의존성 버전과 기본 오프라인 빌드 정책은 별도 요청 없이 바꾸지 않는다.

공통 실행 원칙: [evidence-workflow.md](test-autoevermation-harness-plugin/references/evidence-workflow.md). 호스트별 계약: [host-runtime.md](test-autoevermation-harness-plugin/references/host-runtime.md).
