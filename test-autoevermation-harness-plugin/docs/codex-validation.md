# 0.35.0 실행 검증 기록

검증일: 2026-10-08. Windows 11, Python 3.14, MCP SDK 2.3.0(기존 `>=2.2,<3` 범위), Node, JDK 17.0.7, Gradle 8.12, Maven 3.9.9, 번들 Codex CLI/app-server `0.162.0-alpha.2`에서 수행했다. 의존성 선언·플러그인 자체 테스트 파일은 변경하지 않았다. 새 테스트 스위트는 추가하지 않았다.

## 실제 확인한 범위

| 항목 | 결과·근거 |
|---|---|
| portable plugin.json·mcp.json | 선언된 agent-plugins.org 1.0.0 공식 JSON Schema 검증 통과 |
| CLI 로컬 마켓플레이스/설치 | 격리된 Codex 홈에서 marketplace add → plugin add → list; 0.35.0 installed/enabled 확인 |
| 앱 서버 스킬 로딩 | 실제 설치 캐시를 `skills/list(forceReload:true)`로 로드; 스킬 15개, 파싱 오류 0 |
| 앱 서버 MCP 연결 | `mcpServerStatus/list`에서 repo-ast 5개, spec-doc 4개, build-test 11개 도구 로딩, toolsError 없음 |
| 직접 stdio MCP | Node → bootstrap → SDK2 연결로 health 3종, AST 4개 도구, 스펙 인덱싱·검색·추출, 빌드 감지 호출 확인 |
| 프로젝트 루트 | Codex root 누락/상대 root 거부, root 밖 입력 읽기 거부, 기존 환경 경계 밖 root 거부 확인 |
| 스펙 인덱스 | A 인덱싱 후 B root 검색 시 `SPEC_DOC_ROOT_MISMATCH`; A 내부 상대 경로 추출 성공 |
| 한글·공백 경로 | 별도 한글 프로젝트와 영속 데이터 디렉터리에서 AST·스펙 처리·jar 영속화 성공 |
| JavaParser 미설치 | jar 없는 배포 복사본의 실제 stdio 호출에서 `JAVAPARSER_REQUIRED`; 파서 대체 없음 |
| Claude/Codex MCP 호환 | 동일 입력의 Claude root 생략 호출과 Codex 명시 root 호출에서 AST·스펙·Spring 프로파일 전체 안정 payload 일치 |
| JavaParser 빌드 | 기존 Maven wrapper `mvnw.cmd -q -DskipTests package` 성공 |
| Gradle·Maven 통합 실행 | 기존 `tests/integration/verify_real_builds.py` 수정 없이 실행, ASCII 프로젝트 경로에서 최종 exit 0 |
| 실패/보정·커버리지 | 위 통합 실행으로 한글 메서드 선택, unit/integration task 분리, 전체 skip·없는 테스트 거부, 컴파일 실패·보정, JaCoCo 포함/제외 범위와 게이트 확인 |
| 승인·적합성·staleness | 기존 prompt/pipeline/result/staleness 검사 재사용; Codex 호스트 지침을 읽기 전용 리뷰하여 승인 전 생성 보류, LSP false, 낡은 결과 재사용 금지 확인. 실제 대화형 전체 실행과는 구분 |

최종 통합 실행은 Spring Boot 3.2.0/JUnit Jupiter/JaCoCo 0.8.12를 사용하는 저장소의 기존 fixture를 그대로 사용했다. Windows 기본 소스 인코딩 차이를 보정하기 위해 **검증 전용** Gradle 홈의 init 스크립트에서 JavaCompile `options.encoding = "UTF-8"`를 설정했다. 프로젝트/플러그인의 빌드 파일이나 의존성 버전을 수정하지 않았다. 초기 의존성 다운로드는 이 fixture에 한해 기존 runner의 `online=True`로 허용했고 후속 실행은 기본 오프라인이었다.

## 기존 전체 검사

플러그인 디렉터리에서 `PYTHONUTF8=1`을 설정하고 SDK2 가상환경의 Python으로 실행:

```text
python -m unittest discover -s tests -q
```

최종 결과: **197개 중 190 통과, 4 실패/오류, 3 건너뜀**. 네 실패는 변경 전 `67bb22f`의 별도 보관본에서도 동일하게 재현했다. 원본 실행은 jar 미빌드로 추가 3개가 건너뛰어 총 6개 skip이었다.

- `test_task_discovery_does_not_lose_tasks_to_log_tail`: 기존 테스트의 `server` 미정의 NameError.
- `test_symlink_alias_into_test_tree_is_still_guarded`, `test_symlink_alias_into_workspace_is_still_guarded`: Windows 심볼릭 링크 생성 권한 부족(WinError 1314).
- `test_task_reports_do_not_delete_or_mix_unit_reports`: 기존 POSIX `/integrationTest/` 경로 구분자 단언과 Windows 경로 차이.
- 3개 skip: POSIX 전용 stdio fixture. Windows stdio는 위 실제 MCP 호출로 별도 확인했다.

테스트 파일을 고쳐 결과를 통과로 만들지 않았다. 전체 검사 통과라고 보고하지 않는다.

## 확인된 환경 제한과 미실행 범위

- 깊은 격리 Codex 홈에서는 SDK 설치가 Windows 긴 경로 제한에 걸려 MCP 초기화가 실패했다. 짧은 별도 홈에서 공식 bootstrap 재실행 후 앱 서버 MCP 3종 연결이 성공했다. 시스템 레지스트리/전역 설정은 변경하지 않았다.
- **한글·공백 프로젝트 경로에서 Gradle 통합 실행은 통과**했다. 같은 경로의 Maven/JDK 17.0.7/JaCoCo 0.8.12 조합은 테스트 실행은 성공했지만 에이전트가 깨진 경로의 `jacoco.ex`에 데이터를 기록해 정규 `jacoco.xml`을 만들지 못했다. 하네스는 `JACOCO_REPORT_NOT_FOUND`로 거부했다. 이 환경의 Maven 커버리지는 ASCII 프로젝트 경로에서 검증했다. 한글 Maven 경로의 전체 성공을 주장하지 않는다.
- 실제 데스크톱 Plugins 화면에서 클릭 설치·표시를 확인하지 않았다. 앱이 사용하는 **app-server 프로토콜**의 설치본 로딩과 연결을 확인한 것이다.
- Codex/Claude의 모델을 통한 대화형 승인 → 생성 → 보정 전체 세션은 실행하지 않았다. 공용 MCP·기존 검사·지침 리뷰 결과를 전체 대화형 E2E 통과로 해석하지 않는다.
- 원격 Git 마켓플레이스는 이번 로컬 변경을 아직 push하지 않았으므로 해당 버전의 원격 설치는 실행하지 않았다. 로컬 설치를 확인했으며 Git 설치 명령은 CLI 공식 도움말과 패키징 계약에 맞췄다.

일회성 원시 실행 자료는 저장소의 무시된 `_workspace/`에 `mcp-live.json`, `parity-boundary.json`, `app-server-evidence.json`, `app-server-mcp-short.json`, `real-builds-final/results.json` 등으로 남겼다. 초기 실패 자료도 보존하며 배포 패키지에 포함하지 않는다.
