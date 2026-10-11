# Codex 플러그인 설치·사용 가이드 (0.35.1)

내부 구성요소와 데이터 흐름은 [구조 문서](ARCHITECTURE.md)를 참고한다.

이 가이드는 Codex 앱과 CLI에서 Spring 프로젝트의 테스트를 생성하고, JUnit·JaCoCo·시나리오 적합성으로 결과를 확인하는 절차를 설명한다. **설치 → 대상 프로젝트 열기 → 환경 준비 → 전체 실행 → 시나리오 승인 → 결과 확인** 순서로 진행한다.

현재 작업 버전: 0.35.1(로컬 설치). 공개 main의 0.35.0 Git 설치는 기존 검증 기록이다. 확인일: 2026-10-08. Codex CLI/app-server `0.162.0-alpha.2`를 사용했다. 0.35.1 검증은 [호환성 수정 기록](compatibility-remediation.md)을 참조한다. 다른 Codex 버전의 명령·화면은 해당 버전의 도움말을 확인한다. 실제 검증 범위와 환경 제한은 [검증 기록](codex-validation.md)에 남겼다.

- [준비 사항](#1-준비-사항)
- [앱·CLI 설치](#2-앱cli-설치)
- [첫 테스트 생성](#3-첫-테스트-생성)
- [결과 확인](#4-결과-확인)
- [재실행과 개별 작업](#5-재실행과-개별-작업)
- [업데이트·제거](#6-업데이트제거)
- [문제 해결](#7-문제-해결)
- [Codex 동작과 참고 문서](#8-codex-동작과-참고-문서)

## 1. 준비 사항

| 항목 | 필요한 환경 |
|---|---|
| Codex | 플러그인을 지원하는 앱 또는 CLI. CLI는 `codex plugin --help`로 지원 여부 확인 |
| Node.js | `node`가 PATH에 있어야 MCP 공용 런처를 시작할 수 있음 |
| Python | 3.10 이상. 런처가 플러그인 전용 환경에 `mcp[cli]>=2.2,<3` 준비 |
| 분석용 Java | JavaParser 빌드·실행에 JDK 17 이상. Maven wrapper가 번들되어 시스템 Maven은 필수가 아님 |
| 테스트 실행 Java | 대상 Spring Boot·Mockito·빌드 도구 버전에 맞는 JDK. 분석용 JDK 조건과 별도로 확인 |
| 대상 프로젝트 | Gradle 또는 Maven Spring 프로젝트, 테스트할 패키지·클래스, 스펙 문서 또는 확정할 요구사항 |

터미널에서 기본 도구를 확인한다:

```text
codex --version
codex plugin --help
node --version
java -version
```

Python은 Windows에서 `py -3 --version`, macOS/Linux에서 `python3 --version`으로 확인한다. Python이 없으면 런처가 관리형 Python 설치를 시도한다. 자동 설치를 원하지 않으면 `HARNESS_AUTO_PYTHON=0`으로 시작하고 Python을 직접 준비한다.

초기 Python 런타임·JavaParser 빌드 의존성 준비에는 네트워크가 필요할 수 있다. **대상 프로젝트의 테스트 빌드는 기본 오프라인**이다. 캐시에 의존성이 없다면 하네스가 안내하는 온라인 priming 승인/옵트인 절차를 따른다.

## 2. 앱·CLI 설치

### GitHub에서 설치

아래 명령은 **터미널**에 입력한다. 저장소를 직접 clone하지 않아도 된다.

```text
codex plugin marketplace add 1223v/test-autoevermation-harness --ref main
codex plugin add test-autoevermation-harness-plugin@test-autoevermation-harness
codex plugin list --json
```

마지막 출력의 `installed` 배열에서 다음 값을 확인한다:

```json
{
  "pluginId": "test-autoevermation-harness-plugin@test-autoevermation-harness",
  "version": "0.35.0",
  "installed": true,
  "enabled": true
}
```

위는 확인할 필드만 발췌한 예시다. 향후 릴리스에서는 `version`이 달라질 수 있다. 0.35.0은 게시된 GitHub `main`에서 실제 설치를 확인했다.

### Codex 앱에서 설치·사용

1. CLI를 사용할 수 있으면 위 Git 마켓플레이스 등록 명령을 실행한다. 이미 `plugin add`까지 성공했다면 앱에서는 설치 상태와 활성화를 확인한다.
2. 앱을 다시 시작하고 **Plugins 디렉터리**를 연다.
3. 마켓플레이스 소스 **Test Autoevermation Harness**를 선택한다. 플러그인 `test-autoevermation-harness-plugin`을 설치하고 활성화한다.
4. 테스트를 생성할 **Spring 프로젝트 폴더**를 열고 새 대화를 시작한다.
5. 아래 환경 준비 요청을 입력한다. 플러그인·스킬 선택 화면에서 이 플러그인의 스킬을 선택해도 된다.

앱만 사용한다면 아래 로컬 설치 절의 첫 두 명령(`git clone`, `cd`)으로 저장소를 준비하고, `codex plugin` 명령은 생략한다. **그 저장소 루트**를 앱의 프로젝트로 열고 재시작하면 로컬 카탈로그를 선택해 설치할 수 있다. 설치 후 작업할 프로젝트를 대상 Spring 프로젝트로 바꾼다. 상위 폴더만 열면 `.agents/plugins/marketplace.json`이 검색되지 않을 수 있다.

이 플러그인은 이 저장소의 마켓플레이스로 배포한다. 공개 디렉터리 제출은 포함하지 않으므로 기본 공개 소스의 검색 결과만으로 설치 여부를 판단하지 않는다. 앱 메뉴 명칭은 버전에 따라 달라질 수 있다. 데스크톱 화면의 클릭 설치는 이 세션에서 직접 검증하지 않았다.

### 로컬 저장소에서 설치

소스를 수정하며 사용하거나 이미 clone한 저장소로 설치할 때 사용한다. **Git 설치와 로컬 설치 중 한 경로를 선택한다.**

```text
git clone https://github.com/1223v/test-autoevermation-harness.git
cd test-autoevermation-harness
codex plugin marketplace add .
codex plugin add test-autoevermation-harness-plugin@test-autoevermation-harness
codex plugin list --json
```

이미 저장소가 있으면 clone을 생략한다. 다른 폴더에서 등록할 때는 `codex plugin marketplace add "C:\tools\test-autoevermation-harness"`처럼 **저장소 루트의 절대 경로**를 사용한다. 내부의 `test-autoevermation-harness-plugin` 폴더가 아니라 `.agents/plugins/marketplace.json`이 있는 폴더다.

### CLI에서 대상 프로젝트 열기

설치 후에는 하네스 저장소를 벗어나 테스트할 프로젝트에서 Codex를 시작한다. Windows PowerShell 예시:

```powershell
Set-Location 'C:\work\order-service'
codex
```

macOS/Linux 예시:

```bash
cd /path/to/order-service
codex
```

CLI 대화 안에서는 `/plugins`로 활성화 상태를, `/mcp`로 서버·도구 목록을 살펴볼 수 있다. **목록 표시만으로 연결 검증이 끝나지는 않는다.** 다음 단계에서 MCP `health` 3종을 실제로 호출해야 한다.

## 3. 첫 테스트 생성

이 절의 `text` 블록은 **Codex 대화에 입력할 요청**이다. 터미널 명령이 아니다. 예시 경로·스펙 파일·패키지는 실제 프로젝트에 맞게 바꾼다. macOS/Linux에서는 절대 경로 `/path/to/order-service`를 사용한다.

### 환경 준비

```text
test-autoevermation-harness-plugin의 setup-harness를 사용해 환경을 준비해줘.
projectRoot는 C:\work\order-service야.
Codex 호스트 지침을 읽고 MCP 3종의 health를 실제 호출해서 확인해줘.
```

`setup-harness`는 Python/MCP 런타임, JavaParser 영속 jar, 분석·실행 JDK를 확인하고 필요한 준비를 안내한다. Codex에는 JDT LS 설치나 Claude 상태줄 설정이 필요 없다. 준비가 실패하면 원인을 해결한 뒤 이 요청부터 다시 실행한다.

성공 확인에는 `repo-ast`, `spec-doc`, `build-test`의 실제 `health` 응답과 유효한 JavaParser jar가 필요하다. `setup-harness`는 환경 준비 단계이며, 생성 대상·커버리지 설정은 다음 단계의 `configure-harness`가 담당한다.

### 전체 파이프라인 요청

```text
test-autoevermation-harness-plugin의 full-pipeline을 실행해줘.
projectRoot: C:\work\order-service
스펙 문서: docs/orders.md
테스트 대상: com.example.order 패키지
현재 프로젝트의 Spring·Java·빌드 버전을 확인해서 설정해줘.
커버리지 임계값과 제외 범위는 설정 단계에서 확인해줘.
시나리오를 먼저 문서로 보여주고, 내가 승인한 시나리오만 테스트로 생성해줘.
생성한 테스트를 실행·보정하고 JaCoCo와 시나리오 적합성까지 확인해줘.
```

스펙 입력의 상대 경로는 `projectRoot` 기준이다. 기본 스펙 접근 범위는 `docs`, `specs`, `requirements`다. 스펙 위치나 요구사항이 불명확하면 하네스의 질문에 답해 확정한다.

새 설정이 필요하면 `full-pipeline`이 먼저 `configure-harness`를 사용한다. 빌드 도구·Spring/Java 버전, 대상, LINE/BRANCH/METHOD/CLASS 커버리지 임계값·제외 범위를 확인한다. 유효한 기존 설정을 재사용할 때도 환경·현재 버전·결과의 최신 여부는 다시 확인한다. 환경이 부족하면 구체적인 변경·다운로드를 묶어 동의를 받고 setup-harness로 준비한 뒤 원래 작업을 재개한다. 재시작이 필요하면 재개 지점을 보존한다.

진행 순서는 설정 → 스펙·AST·소스 분석 → 리팩토링 권고 기록·기본 대상 포함 → 시나리오 저장·승인 → 테스트 생성 → JUnit 실행·실패 보정 → JaCoCo → 시나리오 적합성 검증·보정 → 최종 보고다. 리팩토링 권고의 대상 포함 여부는 운영 코드 리팩토링을 자동 승인하는 의미가 아니다.

### 시나리오 승인에 답하기

하네스가 `test_docs/scenarios/<id>.md`와 요약을 제시하면 내용을 읽고 범위를 명시해 답한다. 예를 들어:

```text
SC-001과 SC-002는 승인해.
SC-003은 주문 취소 후 재고가 복원되는 조건을 추가해서 다시 보여줘.
SC-004는 이번 생성 대상에서 제외해.
```

시나리오 번호는 실제 제시된 번호를 사용한다. 수정 요청한 시나리오는 변경 내용을 확인하고 승인한다. 질문 도구가 없어도 일반 대화로 질문하고 응답을 기다린다. **무응답·취소·시간 경과를 승인으로 처리하지 않으며, 미승인 시나리오의 테스트 생성은 보류한다.**

### 실행 모드와 질문

처음 설정할 때 빠름·균형(추천)·엄격을 한 번 선택한다.
빠름은 LINE/BRANCH/METHOD/CLASS 80/70/80/100%, 균형은 90/80/90/100%, 엄격은 95/90/95/100%다.
실패·적합성·커버리지 보정을 합쳐 빠름은 총 1회, 균형은 총 3회다. 마지막 수정 뒤에도 실제 검증한다.
엄격과 정책 없는 기존 설정은 기존 무진전 종료 규칙을 유지한다. 기존 임계값·제외는 명시적 모드 변경 전까지 보존한다.
저장 설정·확인 가능한 정보부터 사용하고 누락·충돌만 묶어 질문한다. 리팩토링 권고는 시나리오 승인 때 함께 제시한다.
도메인 호출 스킬 저장은 요청이 있을 때만 진행한다. 모드 수치는 제품 정책이며 공식 권장값이 아니다.

## 4. 결과 확인

완료 보고를 받으면 대상 프로젝트의 다음 파일을 확인한다. 멀티 모듈 프로젝트의 테스트·빌드 리포트는 해당 모듈 아래에 있을 수 있다.

| 파일·위치 | 확인할 내용 |
|---|---|
| `test_docs/INDEX.md` | 시나리오 ↔ 테스트코드 ↔ 실행·적합성 결과를 모은 사람이 읽는 보고서 |
| `test_docs/scenarios/<id>.md` | 승인 범위, given/when/then, 생성 테스트 매핑, 검증 결과 |
| `src/test/java/` | 생성한 테스트 코드. 프로젝트 설정에 따른 실제 생성 경로 확인 |
| `_workspace/00_config-harness.json` | 확정한 대상·빌드·버전·커버리지 설정 (`schemaVersion:2`) |
| `_workspace/04b_approval.json` | 승인·수정·제외 기록 |
| `_workspace/06_run_result.json` | 최신 JUnit 실행·통과·실패 결과와 실제 리포트 경로 |
| `_workspace/08_coverage_result.json` | JaCoCo 수치, `gatePassed`, 잔여 커버리지 부족 목록 |
| `_workspace/09_conformance.json` | 승인된 시나리오의 충족·불일치·누락 결과 |
| `_workspace/pipeline_result.json` | 전체 단계 상태, 경고·오류, 다음 조치 |

JUnit 원본 XML은 보통 Gradle의 `build/test-results/<task>/`, Maven의 `target/surefire-reports/` 또는 `target/failsafe-reports/`에 있다. JaCoCo XML은 보통 Gradle의 `build/reports/jacoco/`, Maven의 `target/site/jacoco/jacoco.xml`에 있다. 사용자 지정 경로는 결과 JSON의 실제 리포트 경로를 따른다.

**완료는 승인 + 최신 유효 JUnit(`passed > 0`, 실패 없음) + 설정 임계값을 통과한 JaCoCo + 최신 시나리오 적합성이 모두 확인된 경우다.** 테스트 통과만으로 전체 완료가 되지 않는다. `partial`이면 남은 항목을, `failed`이면 오류와 해결 안내를 확인한다. 실행하지 못한 단계나 오래된 리포트를 성공 근거로 쓰지 않는다.

## 5. 재실행과 개별 작업

조회는 기존 결과·신선도만 보고한다. 테스트 실행은 실제 실행만, 커버리지 측정은 유효 결과 공유 또는 한 번 실행·측정만 한다. 추가 수정은 명시적 수정·생성·상향 요청에서 수행한다.
executionSummary에는 모드·보정 횟수·중단 이유·재사용 근거가 나온다. 예산 소진 후 partial이면 “계속 보정해줘”라는 명시적 요청으로만 추가 예산을 쓴다. 자동 재개·세션 재시작은 예산을 초기화하지 않는다.


### 중단한 작업 이어가기·소스 변경 후 검증

```text
test-autoevermation-harness-plugin의 full-pipeline으로 이어서 진행해줘.
projectRoot는 C:\work\order-service야.
기존 설정과 승인 범위를 확인하고 detect_pipeline_state로 재개 단계를 판단해줘.
변경된 소스·스펙에 영향받는 단계부터 실행하고, 낡은 결과는 재사용하지 마.
```

`_workspace/`와 `test_docs/`를 남겨 두면 유효한 설정·승인·결과를 확인해 재개할 수 있다. 이전 `status:"ok"`만으로 종료하지 않으며 시나리오 적합성은 매번 다시 확인한다. 커버리지 상향·테스트 재생성도 `full-pipeline`에 요청한다.

### 필요한 작업만 요청하기

각 요청에서 플러그인 이름과 `projectRoot`를 명시하고 아래 스킬 이름을 사용한다. 개별 작업의 완료는 전체 파이프라인 완료와 구분한다.

| 목적 | 스킬 | 요청 예시 |
|---|---|---|
| 런타임·JavaParser 준비 | `setup-harness` | “환경을 준비하고 MCP 연결을 확인해줘” |
| 대상·임계값 설정 | `configure-harness` | “테스트 대상과 커버리지 임계값을 다시 설정해줘” |
| 생성·재생성·재개·커버리지 상향 | `full-pipeline` | “주문 서비스의 승인된 시나리오 테스트를 보완해줘” |
| 기존 테스트 실행 | `run-tests` | “OrderServiceTest를 실행하고 JUnit 결과를 보여줘” |
| 실패 테스트 원인 보정 | `repair-tests` | “방금 실패한 테스트를 원인부터 분석해 보정해줘” |
| 커버리지 측정 | `measure-coverage` | “현재 설정에 따라 커버리지를 측정하고 부족분을 확인해줘” |
| 시나리오 충족 확인 | `verify-scenarios` | “현재 승인 시나리오와 최신 테스트 결과의 적합성을 확인해줘” |
| 지목한 기존 테스트 편집 | `edit-tests` | “이 테스트의 메서드 이름을 바꾸되 시나리오 매핑을 보존해줘” |

`edit-tests` 자체는 테스트를 실행하지 않는다. 편집 후 `run-tests`를 요청하고, 전체 결과를 확정해야 하면 `full-pipeline`으로 이어서 검증한다. 스킬 선행 조건이나 입력이 부족하면 하네스가 안내하는 준비·설정을 먼저 완료한다.

## 6. 업데이트·제거

### Git 설치 업데이트

터미널에서 마켓플레이스를 갱신하고 설치본을 갱신한다:

```text
codex plugin marketplace upgrade test-autoevermation-harness
codex plugin add test-autoevermation-harness-plugin@test-autoevermation-harness
codex plugin list --json
```

앱 또는 CLI 세션을 다시 시작하고 버전·활성화 상태를 확인한다. 로컬 설치는 소스 저장소를 갱신한 뒤 같은 `plugin add` 명령으로 다시 설치한다. Git 설치에는 원격에 push되지 않은 로컬 변경이 반영되지 않는다. 설치 캐시를 직접 편집하지 않는다.

### 제거·비활성화

플러그인만 제거:

```text
codex plugin remove test-autoevermation-harness-plugin@test-autoevermation-harness
```

마켓플레이스 등록도 해제하려면 플러그인 제거 후 실행:

```text
codex plugin marketplace remove test-autoevermation-harness
```

일시적으로 끄려면 앱의 플러그인 관리 화면 또는 CLI 대화의 `/plugins`에서 활성화를 해제한다. CLI에서는 설치된 플러그인을 선택하고 `Space`로 전환할 수 있다. 변경 후 새 세션에서 상태를 확인한다.

## 7. 문제 해결

| 증상 | 확인·해결 방법 |
|---|---|
| `codex plugin` 명령을 인식하지 못함 | `codex --version`, `codex --help` 확인. 플러그인을 지원하는 Codex 버전으로 업데이트하고 해당 버전 도움말 사용 |
| 앱에서 플러그인을 찾지 못함 | `Test Autoevermation Harness` 소스 선택. 로컬은 저장소 루트 열기, Git은 `codex plugin marketplace list`로 등록 확인 후 앱 재시작 |
| 설치했지만 스킬이 보이지 않음 | `plugin list --json`의 installed/enabled 확인. 실제 작업 프로젝트의 설정·조직 정책에서 비활성화되어 있는지 확인 후 새 대화 시작 |
| MCP 미노출·연결 실패 | 플러그인 활성화·Node/Python 확인 후 새 세션에서 `setup-harness` 요청. health 3종의 실제 실패 원인을 해결 |
| `PROJECT_ROOT_REQUIRED` / `INVALID_PROJECT_ROOT` | 실제 존재하는 절대 `projectRoot` 전달. Windows는 드라이브까지 포함한 `C:\work\order-service` 형식 사용 |
| 루트 밖 입력·`PROJECT_ROOT_OUTSIDE_ALLOWLIST` | 올바른 대상 프로젝트와 그 내부 경로 사용. 기존 환경 경계를 임의로 넓히지 않음 |
| `SPEC_DOC_ROOT_MISMATCH` | 현재 프로젝트의 root로 스펙을 다시 인덱싱한 뒤 검색·추출. 다른 프로젝트의 인덱스를 재사용하지 않음 |
| `JAVAPARSER_REQUIRED` / jar 미영속 | `setup-harness`로 JDK17+·JavaParser 빌드·영속화를 완료하고 health 재확인 |
| JDK 버전 충돌·컴파일 실패 | 분석용 JDK와 대상 테스트 실행 JDK를 따로 확인. 현재 Spring/Mockito/빌드 버전의 공식 문서와 컴파일 진단에 따라 해결 |
| 오프라인 의존성 부족 | 필요한 다운로드를 확인하고 기존 온라인 priming 승인/옵트인 절차로 준비한 뒤 재실행 |
| Windows 긴 경로로 SDK 설치 실패 | 실패 경로 확인 후 짧은 데이터 경로 또는 사전 준비한 SDK2 Python으로 런타임 준비 재시도. 전역 설정을 임의 변경하지 않음 |
| Windows에서 한글 Java 소스 컴파일 실패 | Gradle JavaCompile UTF-8 등 대상 빌드의 소스 인코딩 확인. Python UTF-8 설정은 Java 컴파일러 인코딩을 바꾸지 않음 |
| 한글 Maven 경로에서 JaCoCo XML 누락 | [조건부 우회 계약](../references/compatibility-runtime.md#windows-maven의-한글-경로)에 따라 기존 승인 안에서 실제 agent/JVM 옵션·workingDirectory를 확인. ASCII 상대 destfile을 사용한 뒤 최신 exec/XML 검증. 불명확하면 질문·보류 |
| 미해결 Java 심볼 | 소스·컴파일 결과로 의미 확인. 생성에 필요한 의미가 불명확하면 질문하거나 해당 대상 보류 |
| 커버리지 미달·시나리오 불일치 | 최종 JSON과 잔여 목록 확인 후 `full-pipeline`으로 보완. 임계값·제외 범위를 임의 변경해 성공 처리하지 않음 |
| 오래된 결과에서 재개 | `full-pipeline`의 `detect_pipeline_state` 판단에 따라 영향 단계부터 재실행 |

## 8. Codex 동작과 참고 문서

플러그인 설치 위치와 분석 대상은 별개다. `PLUGIN_ROOT`는 설치 폴더, `PLUGIN_DATA`는 영속 런타임·JavaParser 데이터다. MCP의 작업 디렉터리는 설치 폴더이므로 하네스가 프로젝트 접근 호출마다 확정된 절대 `projectRoot`를 `root`로 전달한다. 일반 셸에도 이 변수가 자동 노출된다고 가정하지 않는다.

`REPO_AST_ALLOW_ROOT`·`SPEC_DOC_WORKSPACE`가 별도로 설정되어 있으면 명시 root로 그 경계를 넓힐 수 없다. 스펙 인덱스는 한 프로세스에 한 프로젝트 스냅샷이며 프로젝트를 바꾸면 재인덱싱한다. 수동 런처·jar 준비의 정확한 경로와 환경은 [Codex 어댑터](../references/hosts/codex.md)를 따른다.

| 항목 | Codex에서의 동작 |
|---|---|
| 공용 구성 | 15개 스킬, 11개 역할 문서, MCP 3종 재사용. 역할 문서는 작업 지침이며 전역 에이전트 설정을 설치하지 않음 |
| 코드 분석 | JavaParser·소스·컴파일 결과. JDT LS 필수 조건 없음, `lspAvailable:false` 기록 |
| 실행 방식 | 순차 실행 기본. 제공된 실제 도구가 있으면 독립적인 스펙·AST 분석만 선택적으로 위임 |
| 승인·단계 순서 | 스킬 지침으로 관리. Claude의 강제 위임·쓰기 훅과 상태줄은 실행하지 않음 |
| 설정·결과 | `schemaVersion:2`, 기존 `_workspace/`·`test_docs/` 유지. 선택적으로 `host:"codex"`, `analysisBackend:"javaparser-source"` 기록 |
| 작업 원칙 | 구조·파일 읽기 → 실제 버전의 공식 문서 → 근거 있는 TODO → 실행 → 최신 결과 확인 |

Superpowers의 필요한 원칙은 스킬에 내장되어 **별도 설치가 필요 없다**. 테스트 생성 과정에 의무 RED–GREEN TDD, mutation testing, 플러그인 자체 메타 테스트나 중복 승인 단계를 추가하지 않는다. 생성한 프로젝트 테스트의 실행·보정·커버리지·시나리오 검증은 수행한다.

운영 계약: [호스트 대응표](../references/host-runtime.md), [근거 중심 작업 원칙](../references/evidence-workflow.md), [시나리오 문서](../references/scenario-docs.md), [환경 준비](../references/environment-setup.md). 공용 문서의 Claude 전용 도구·LSP·훅 예시는 Codex 어댑터 지침으로 치환한다. Claude Code 설치·실행은 [종합 가이드](GUIDE.md)를 참고한다.

공식 근거: [OpenAI 패키징·마켓플레이스](https://developers.openai.com/plugins/build/plugins), [CLI 명령·`/plugins`·`/mcp`](https://learn.chatgpt.com/docs/developer-commands), [스킬·플러그인 사용](https://learn.chatgpt.com/docs/skills-and-plugins), [스킬 작성](https://developers.openai.com/plugins/build/skills), [Codex MCP 경로 처리](https://github.com/openai/codex/blob/main/codex-rs/codex-mcp/src/agent_plugin_config.rs).
