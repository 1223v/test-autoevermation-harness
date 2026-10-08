# Codex 앱·CLI 설치와 운영 (0.35.0)

Codex와 Claude Code가 같은 15개 스킬·11개 역할 문서·MCP 3종을 사용한다. Codex는 JavaParser·소스·컴파일 결과로 분석하고 단계별 작업을 순차 수행한다. Claude의 JDT LS·상태줄·강제 위임 훅은 Codex에서 실행하지 않는다. Superpowers의 근거 중심 작업 원칙은 스킬에 내장되어 별도 설치가 필요 없다.

## 설치

표준 패키지는 플러그인 루트 `plugin.json`과 `mcp.json`, 저장소 `.agents/plugins/marketplace.json`이다. 기존 Claude 파일도 함께 배포한다. 공개 디렉터리 제출은 포함하지 않는다.

**로컬 CLI** — 저장소 루트에서 실행한다. 설치된 CLI가 `codex plugin` 명령을 제공하는지 먼저 `codex plugin --help`로 확인한다.

```text
codex plugin marketplace add .
codex plugin add test-autoevermation-harness-plugin@test-autoevermation-harness
codex plugin list
```

**Git CLI** — 이 버전의 카탈로그와 패키지가 원격에 게시된 뒤 사용한다. 아직 push하지 않은 로컬 변경은 Git 설치에 반영되지 않는다.

```text
codex plugin marketplace add 1223v/test-autoevermation-harness --ref main
codex plugin add test-autoevermation-harness-plugin@test-autoevermation-harness
```

**앱** — 이 Git 저장소를 프로젝트로 열고 앱을 다시 시작한다. Plugins 디렉터리에서 `Test Autoevermation Harness` 마켓플레이스를 선택하고 플러그인을 설치/활성화한다. 프로젝트 폴더의 상위 폴더를 열었다면 저장소 카탈로그가 검색되지 않을 수 있으므로 저장소 자체를 열거나 CLI로 저장소의 절대 경로를 등록한다. 설치 후 새 대화에서 플러그인을 선택해 스킬과 MCP 연결을 확인한다. 앱 화면의 설치 확인은 CLI 설치 성공과 별개다.

**업데이트** — 로컬 소스는 파일을 갱신한 뒤 같은 `codex plugin add`로 설치본을 갱신하고 새 세션을 시작한다. Git 소스는 아래처럼 마켓플레이스를 먼저 갱신한다. 앱은 플러그인 업데이트/새로 고침 후 새 대화에서 확인한다.

```text
codex plugin marketplace upgrade test-autoevermation-harness
codex plugin add test-autoevermation-harness-plugin@test-autoevermation-harness
```

제거는 `codex plugin remove test-autoevermation-harness-plugin@test-autoevermation-harness`를 사용한다. CLI 옵션은 설치된 버전의 `--help`를 기준으로 한다.

## 준비와 실행

- Node.js와 Python 3.10+가 필요하다. 공용 런처가 기존 `mcp[cli]>=2.2,<3` 의존성을 준비한다. 자동 Python 설치 비활성화는 `HARNESS_AUTO_PYTHON=0`.
- JavaParser CLI는 JDK 17+와 번들 Maven wrapper로 빌드한다. Codex에는 JDT LS의 JDK 21 조건이 없다. 대상 Spring 프로젝트의 테스트 실행 JDK는 해당 버전 호환성에 맞춘다.
- 초기 런타임·JavaParser 의존성 준비에는 네트워크가 필요할 수 있다. 대상 테스트 빌드는 기본 오프라인이며 기존 온라인 priming 승인/옵트인 정책을 유지한다.
- Windows Gradle 프로젝트의 한글 소스에는 빌드 설정의 JavaCompile UTF-8 인코딩을 확인한다. Python UTF-8 설정이 Java 컴파일러의 인코딩을 바꾸지는 않는다.

대상 프로젝트에서 새 대화를 시작하고 예를 들어 다음처럼 요청한다. 현재 도구 목록에 표시된 플러그인 스킬을 직접 선택해도 된다.

```text
test-autoevermation-harness-plugin의 setup-harness를 사용해
C:\work\주문 서비스 환경을 준비해줘.
```

```text
test-autoevermation-harness-plugin의 full-pipeline을 실행해줘.
projectRoot는 C:\work\주문 서비스,
스펙은 docs/orders.md, 대상은 com.example.order야.
시나리오를 먼저 보여주고 승인받은 다음 테스트를 생성해줘.
```

순서는 환경 준비 → configure-harness의 설정·프로파일/빌드 능력 확인 → 분석 → 시나리오 승인 → 생성·JUnit 실행/보정 → JaCoCo → 시나리오 적합성 검증이다. 질문 도구가 없으면 대화로 묻고 응답을 기다린다. 도구 부재를 CI나 승인으로 간주하지 않는다.

## 경로와 진단

Codex MCP의 작업 디렉터리는 설치 폴더다. `PLUGIN_ROOT`는 설치 위치, `PLUGIN_DATA`는 영속 런타임/JavaParser 데이터다. 분석 대상은 별도의 절대 `projectRoot`이며 프로젝트 접근 도구마다 `root`로 전달한다. 셸에서 수동 준비 시에도 실제 설치/데이터 경로와 `HARNESS_HOST=codex`를 전달한다. 환경변수가 일반 셸에 자동 노출된다고 가정하지 않는다.

```text
repo-ast.health(root="C:\work\주문 서비스")
spec-doc.health(root="C:\work\주문 서비스")
build-test.health(root="C:\work\주문 서비스")
repo-ast.extract_test_targets(paths=["src/main/java"], root="C:\work\주문 서비스")
spec-doc.index_docs(paths=["docs"], root="C:\work\주문 서비스")
```

위는 도구 의미를 보이는 표기다. 호출 시 현재 세션에 노출된 실제 MCP 도구 이름과 스키마를 사용한다.

| 증상 | 대응 |
|---|---|
| `PROJECT_ROOT_REQUIRED` / `INVALID_PROJECT_ROOT` | 확정된 절대 기존 디렉터리를 root에 전달 |
| `PROJECT_ROOT_OUTSIDE_ALLOWLIST` | 환경변수 경계를 확인하고 올바른 프로젝트에서 실행; 경계를 임의 확장하지 않음 |
| `SPEC_DOC_ROOT_MISMATCH` | 해당 root로 `index_docs` 재실행 후 검색·추출 |
| `JAVAPARSER_REQUIRED` / jar 미영속 | setup-harness E6 빌드·persist 후 health 재확인 |
| Windows 긴 경로로 SDK 설치 실패 | 짧은 데이터 경로 또는 사전 준비한 SDK2 Python을 사용하고 bootstrap 재확인 |
| Maven/JDK17에서 한글 경로 JaCoCo 누락 | 정규 XML 없이는 완료하지 않음; 검증된 ASCII 프로젝트 경로 사용, [환경 제한](codex-validation.md) 확인 |
| MCP 미노출/연결 실패 | 플러그인 활성화·런처 실행·런타임 준비 확인 후 새 세션에서 health 3종 실호출 |
| 미해결 심볼 | 소스/컴파일 진단으로 확인; 의미 불명확한 대상은 질문 또는 보류 |
| stale 결과 | detect_pipeline_state의 영향 단계부터 다시 실행 |

`REPO_AST_ALLOW_ROOT`와 `SPEC_DOC_WORKSPACE`가 별도로 설정되어 있으면 명시 root로도 그 범위를 넓힐 수 없다. 스펙 인덱스는 한 프로세스에 한 프로젝트 스냅샷이며 다른 프로젝트로 바꾸면 재인덱싱한다.

## 호환성과 완료 기준

`HarnessConfig`는 schemaVersion 2를 유지하며 선택적으로 `host:"codex"`, `analysisBackend:"javaparser-source"`를 기록한다. Codex의 `lspAvailable`은 false다. `_workspace/`와 `test_docs/` 산출물 구조는 그대로다.

Codex의 시나리오 승인과 단계 순서는 **스킬 지침으로 관리**한다. Claude처럼 훅이 물리적으로 강제하지 않는다. 가짜 spawn 마커를 생성하지 않는다. 완료에는 유효한 승인, 최신 JUnit, 현재 임계값을 통과한 JaCoCo, 최신 시나리오 적합성 결과가 모두 필요하다. 실패·미달·불일치·보류 대상을 성공으로 집계하지 않는다.

운영 정본: [Codex 어댑터](../references/hosts/codex.md), [공통 작업 원칙](../references/evidence-workflow.md), [호스트 대응표](../references/host-runtime.md). 실제 검증과 미실행 범위: [0.35.0 검증 기록](codex-validation.md).

근거: [OpenAI 패키징](https://developers.openai.com/plugins/build/plugins), [스킬 작성](https://developers.openai.com/plugins/build/skills), [Codex의 portable MCP 경로 처리](https://github.com/openai/codex/blob/main/codex-rs/codex-mcp/src/agent_plugin_config.rs).
