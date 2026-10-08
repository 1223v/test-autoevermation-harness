# Codex 앱·CLI 어댑터

## 실행과 도구

스킬 본문의 공용 데이터 계약과 단계 절차를 읽고 수행한다. `Agent(...)` 예시는 해당 `agents/<role>.md`를 읽어 그 역할의 작업을 현재 대화에서 실행하는 것으로 치환한다. frontmatter의 Claude 전용 도구 목록은 Codex 에이전트 설정이 아니다. 역할의 읽기/쓰기 책임은 지키되 전역 `config.toml`이나 에이전트 설정을 설치하지 않는다.

순차 실행이 기본이다. 스펙 인제스트와 AST 분석이 서로 독립이고 실제 위임 도구가 제공된 경우에만 선택적으로 위임할 수 있다. 실제 도구 스키마를 읽고 대상 루트·역할 문서·입력·출력 계약을 전달한다. 읽기 전용 작업 결과는 메인이 검토해 저장한다. 이후 생성·실행·보정은 공용 단계 순서를 지킨다. `Agent`라는 이름이나 `subagent_type` 인자를 Codex에 가정하지 않는다.

질문은 메인 대화에서 현재 사용 가능한 도구(예: 해당 모드에서 지원하는 `request_user_input` 또는 `request_user_input_async`)의 실제 스키마와 용도 제약을 따른다. 승인에 쓸 수 없는 질문 도구이면 일반 대화로 묻는다. 질문 도구가 없으면 일반 대화로 질문하고 **사용자 응답을 기다린다**. 거부·취소·무응답·시간 경과는 승인도 CI 전환도 아니다. 독립적인 읽기 작업만 계속할 수 있다. 명시적 입력 불가 실행/`skipInterview`의 기존 정책은 유지하되 필수 값 누락 시 `INTERVIEW_REQUIRED`로 중단한다. CI 시나리오 승인 정책을 적용했다면 그 모드와 근거를 기록한다.

## 경로와 환경 준비

MCP는 설치 폴더에서 시작하므로 cwd를 분석 대상이라고 가정하지 않는다. `projectRoot`를 사용자의 요청·현재 작업공간에서 확인한 **절대 기존 디렉터리**로 확정한다. 애매하면 질문한다. 모든 repo-ast·spec-doc 프로젝트 접근 호출에 `root=projectRoot`를 전달한다. build-test의 `root`도 반드시 명시한다. 상대 입력 경로는 이 루트 기준이다. 범위 이탈 오류에 환경변수를 넓혀 대응하지 않는다.

Codex가 MCP에 주입한 `PLUGIN_ROOT`는 설치 폴더, `PLUGIN_DATA`는 업데이트를 넘어 유지되는 데이터 폴더다. 일반 셸에 이 변수가 없다면 실제 설치 경로/health의 경로를 확인하여 명령 인자로 사용한다. 플레이스홀더를 그대로 실행하지 않는다. Python 실행은 공용 `node <PLUGIN_ROOT>/mcp/launch.cjs`를 사용한다. 런처는 Python 자식에 UTF-8을 전달한다.

`setup-harness`는 다음 호스트 체크리스트를 사용한다. 본문의 JDT LS·상태줄 항목과 JDK 21 필수 조건은 Claude 전용이다.

1. E1~E3: Node, Python 3.10+, 기존 `mcp[cli]>=2.2,<3` 런타임과 MCP 3종. `node <PLUGIN_ROOT>/mcp/launch.cjs --ensure-only`로 준비한다. Codex의 MCP 시작 시에도 bootstrap이 실행된다.
2. E3b: `repo-ast.health(root=projectRoot)`, `spec-doc.health(root=projectRoot)`, `build-test.health(root=projectRoot)`를 **실제로** 호출한다. `scopeError`가 없어야 한다. 등록/연결 실패 시 Codex 플러그인 활성화와 세션 재시작을 안내하고 중단한다.
3. E4~E6: JavaParser CLI의 `pom.xml` release 17에 맞는 JDK **17+**, 번들 Maven wrapper, 유효한 영속 jar가 필요하다. `persist_astcli_jar.py --check`로 최신 여부를 확인한다. 필요 시 `<PLUGIN_ROOT>/mcp/javaparser-cli`에서 OS에 맞는 `mvnw` 또는 `mvnw.cmd -q -DskipTests package` 후 `node <PLUGIN_ROOT>/mcp/launch.cjs script <PLUGIN_ROOT>/scripts/persist_astcli_jar.py`로 `PLUGIN_DATA/javaparser`에 영속화한다. 셸 실행 시 `HARNESS_HOST=codex`와 확인된 `PLUGIN_DATA`를 자식 환경에 전달한다.
4. E7 JDT LS와 S1 상태줄은 **not-applicable**로 기록한다. 설치하거나 연결을 요구하지 않는다. `setup-statusline`은 Codex에서 미지원임을 알리고 종료한다.
5. E10: 대상 Spring/Mockito/ByteBuddy에 맞는 **테스트 실행 JDK**를 별도로 확인한다. E8·E9 버전 감지와 E11·E12 JaCoCo/캐시 준비는 기존처럼 configure-harness 담당이다. 프로젝트 빌드 변경과 온라인 priming은 기존 동의/옵트인 정책을 따른다. 기본 오프라인 실행은 유지한다.

`configure-harness`와 `full-pipeline`의 E-verify는 이 목록의 필수 항목만 재확인한다. 환경을 자동 변경하지 않고 미충족이면 setup-harness를 안내한다. JavaParser 미설치·실패는 `JAVAPARSER_REQUIRED` 등 실제 실패로 보고하며 정규식 파서로 대체하지 않는다.

## 분석과 설정

`HarnessConfig`는 `schemaVersion:2`, 기존 키와 산출물 경로를 유지한다. 선택 메타데이터로 `host:"codex"`, `analysisBackend:"javaparser-source"`를 저장하고 `lspAvailable:false`로 기록한다. 이 조합은 정상 지원 경로다. 본문의 LSP 미가용 하드 중단과 `lspAvailable:true` 예시는 Claude에만 적용한다. 기존 설정에 메타데이터가 없으면 현재 호스트를 확인해 채우고 실제 역량을 재확인한다.

analyze-ast는 JavaParser MCP를 사용한다. analyze-source와 refactor-advisory는 JavaParser 심볼·호출 자료, 관련 소스·빌드 설정, 실제 컴파일 진단을 교차 확인한다. `resolve_symbol`은 클래스패스 전체를 해결하는 LSP가 아니므로 상속·오버로드·생성 코드 의미를 추측하지 않는다. 해결하지 못한 심볼과 영향 대상을 `warnings`와 `evidence`에 기록한다. 생성에 필요한 의미가 불명확하면 질문하거나 해당 대상만 보류(`partial`)한다. 보류 대상을 충족/커버리지 제외로 처리하지 않는다. 필수 대상이 모두 보류되면 생성을 중단한다.

## 단계·승인·재개

공용 단계: 설정 → 스펙 → AST → 소스 → 리팩토링 권고/대상 결정 → 시나리오 저장 → **승인** → 생성 → JUnit 실행/보정 → JaCoCo 게이트 → 시나리오 적합성/보정 → 최종 집계. 역할별 `_workspace/00`~`09` 산출물 이름과 `test_docs/` 구조를 유지한다. 참조하는 스킬의 역할 문서·출력 스키마·중단 기준을 사용한다.

- 승인된 시나리오가 없으면 5단계 생성·해당 테스트 파일 쓰기를 보류한다. 승인 문서는 실제 승인 범위·수정·제외를 반영한다. 별도 계획 승인이나 중복 리뷰 단계를 덧붙이지 않는다.
- Codex 매니페스트의 `hooks:{}`는 의도적인 설정이다. Claude의 spawn/Write 가드는 실행되지 않는다. `.markers/`를 만들거나 위임 증거를 위조하지 않는다. 단계 완료 즉시 실제 결과를 저장하고 선행 조건을 메인이 확인한다. 기존 Claude 마커는 새 Codex 실행의 증거로 사용하지 않는다.
- 재개 시 `detect_pipeline_state(root=projectRoot, ...)`에 현재 config의 임계값·대상·제외를 전달한다. `schemaVersion:2`, 프로젝트·대상 일치, 현재 승인, `staleness`를 확인하고 추천 단계보다 뒤로 건너뛰지 않는다. Codex는 `allowedArtifacts` 훅 마커를 만들지 않는다. 반환된 실제 검사 결과와 영속 파일 경로를 `evidence`에 남기며 유효한 기존 산출물만 재사용한다. 확인할 수 없는 산출물을 `status:"reused"` stub으로 채우지 않는다.
- 오래된 JUnit/JaCoCo/시나리오/설정은 영향 단계부터 재실행한다. 이전 `pipeline_result.json`의 성공만으로 종료하지 않는다. 9단계 적합성은 매번 새로 확인한다.
- 실패 테스트는 원인 분석 후 최소 수정하고 6→8→9를 다시 수행한다. 기존 무진전 3회, 적합성 최대 3라운드·동일 unmet 중단 규칙을 유지한다. 커버리지 미달/시나리오 불일치는 `partial`/잔여 목록으로 보고하며 임의 제외하지 않는다.
- 완료는 현재 소스에 대한 승인, 최신 유효 JUnit(`passed>0`, 실패 없음), 현재 임계값 JaCoCo, 시나리오 적합성이 모두 확인된 경우에만 기록한다. 실제 실행하지 않은 단계는 완료로 표시하지 않는다.
- 훅 기반 timing은 Codex에서 생략한다. 관측한 시간만 선택적으로 기록하며 토큰 수를 추정해 쓰지 않는다.

설정 마지막의 프로젝트용 호출 스킬을 사용자가 저장하도록 요청한 경우 Codex는 `<projectRoot>/.agents/skills/<name>/SKILL.md`에 저장한다. 이름 충돌 시 확인하며 플러그인 캐시나 전역 에이전트 설정에 쓰지 않는다. 호출 본문에는 Codex의 실제 스킬 선택 방식(예: `$test-autoevermation-harness-plugin:full-pipeline` 또는 자연어 요청)과 확정된 설정을 쓴다.
