# 환경 세팅 체크리스트 (Preflight SSOT)

이 문서는 하네스를 돌리기 **전에** 미리 끝내야 하는 **환경 세팅의 단일 출처(SSOT)**다.
fallback은 파이프라인 도중에 "마주치는" 것이 아니라, 여기서 **선제적으로 세팅**해 제거한다.

> 정책 연계: 런타임 의사결정(스펙 읽기불가·건너뛰기 등)은 [fallback-policy.md](./fallback-policy.md)를 따른다.
> 이 문서는 그중 **환경·역량·버전 감지** 항목(#1·#2·#3·#4·#5·#6·**#20** + 테스트 실행 JDK)을 **시작 시점에 일괄 처리**하는 절차다.

## 역할 분담 (v0.24.0 — 세팅과 실행의 분리)

| 주체 | 담당 | 성격 |
|---|---|---|
| **`setup-harness` 스킬** | **E1~E10 환경 세팅 + 상태줄(S1) 설치** | **설치·빌드·프로비저닝을 실제로 수행**한다. 사용자가 명시적으로 1회(또는 환경이 깨졌을 때) 실행 |
| `configure-harness` 스킬 | **E-verify 프로브**(시작 게이트) → 0.5단계 E8·E9 감지 → 0.6단계 E11·E12 | 세팅을 **수행하지 않는다**. 프로브 실패 시 하드 중단 |
| `full-pipeline` 스킬 | **E-verify 프로브**(configure-harness를 건너뛰는 재사용·재개 경로에서 직접 실행) | 세팅을 **수행하지 않는다**. 프로브 실패 시 파이프라인 미시작 |

## 핵심 원칙

1. **세팅과 실행의 분리.** 환경 세팅(E1~E10)의 수행 주체는 **`setup-harness` 스킬 단 하나**다. `full-pipeline`/`configure-harness`는 시작 시 아래 **「E-verify 검증 프로브」만** 실행하며, **어떤 항목도 스스로 세팅하지 않는다** — 미충족이면 파이프라인을 시작하지 않고 `setup-harness` 실행을 안내하며 하드 중단한다.
2. **함께 세팅 (대화형, setup-harness 안에서).** 자동으로 고칠 수 있는 항목은 **항목별로** `AskUserQuestion("지금 함께 세팅할까요?")`로 묻고, "예"면 그 자리에서 설치/빌드 → 재검증 → 체크. 침묵 진행·임의 degrade 금지.
3. **항상 자동 세팅 (비대화형/CI, setup-harness 안에서).** `claude -p`/CI에는 질문할 수 없으므로 **결정적 세팅 항목**(pip 설치·jar 빌드 등 고정 명령으로 고칠 수 있는 것)은 **자동 수행**한다. 자동 수행이 실패하거나 **비결정적 항목**(버전 미감지·프로파일 충돌처럼 사람이 골라야 하는 것)은 `status:"failed"` + remediation으로 **하드 중단**한다.
4. **TODO 가시화.** 각 항목을 TodoWrite 항목으로 만들어 `pending → in_progress → completed`로 체크해 나간다. 사용자/로그에 진척이 보이게 한다.
5. **검증 후 체크.** 세팅 액션 뒤에는 반드시 **재감지**해서 통과를 확인한 뒤에만 completed로 표시한다.

---

## 체크리스트 (TODO 항목) — 수행 주체: `setup-harness`

각 항목: **감지(detect) → (미충족 시) 세팅 → 검증(verify)**. `auto`=결정적 자동 세팅 가능, `assist`=사용자와 함께/안내 필요.

> **아래 E1~E10의 "세팅" 컬럼을 실행하는 주체는 `setup-harness` 스킬이다.** E8·E9(데이터 감지)는 configure-harness 0.5단계, E11·E12(빌드 능력·캐시)는 configure-harness 0.6단계에서 처리한다(`mutation.enabled` 인터뷰 결과에 의존하므로 세팅 단계로 앞당길 수 없다).

| # | 항목 | 감지 | 세팅 종류 | 대화형 동작 | CI 동작 | 연계 |
|---|---|---|---|---|---|---|
| E1 | **Python 3.10+** | `python3 -c "import sys;assert sys.version_info>=(3,10)"` (Windows: `py -3 -c ...` 또는 `python -c ...`) 또는 `${CLAUDE_PLUGIN_DATA}/python-path` 핀 존재 | auto(전 OS) | **자동**(v0.15.0+ 전 OS): `node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs --ensure-only` — PATH에 3.10+ 없으면 uv(무-sudo; POSIX `install.sh` / Windows `install.ps1`)로 관리형 Python 자동 설치. 실패 시에만 설치 경로 안내(brew/apt/winget/python.org). `HARNESS_AUTO_PYTHON=0`이면 assist로 강등. POSIX 전용 구진입점 `run-server.sh`는 수동 폴백으로 유지 | 동일 자동, 실패 시 하드 중단 + remediation | MCP 런타임 |
| E2 | **MCP Python SDK** (`mcp[cli]>=1.2.0`) | `python3 -c "import mcp"` 성공 **또는** bootstrap venv marker 존재 | auto | **자동**(v0.12.0+): `python3 ${CLAUDE_PLUGIN_ROOT}/mcp/bootstrap.py --ensure-only` — `${CLAUDE_PLUGIN_DATA}/venv`에 설치, 시스템 python 비오염. 실패 시에만 `AskUserQuestion` → pip 수동 폴백 | **자동** bootstrap 동일, 실패 시 중단 + pip 폴백 remediation | policy #1 |
| E3 | **MCP 서버 3종 등록** (repo-ast·spec-doc·build-test) | `.mcp.json` 존재 + 각 서버 import 가능(`python3 mcp/<server>.py --help` 또는 모듈 로드) | auto | 누락 서버를 `.mcp.json`에 맞춰 점검, import 실패는 E2로 귀결. 재로딩 안내 | 자동 점검, import 실패면 중단 | `.mcp.json` |
| E3b | **MCP 라이브 연결 검증** | 메인 루프가 `repo-ast-mcp.health`·`spec-doc-mcp.health`·`build-test-mcp.health` 3종 도구를 **실제 호출**해 응답 확인 (E3의 import 검사로는 플러그인 MCP 등록 실패를 못 잡음) | auto | 실패 시 하드 중단 + remediation(① 플러그인 활성화 확인 → ② `node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs --ensure-only` 수동 실행 → ③ `/reload-plugins` 또는 Claude Code 재시작 → ④ SessionStart 훅 stderr 확인) | 동일 절차로 하드 중단(질문 없이 자동 판정) | policy #20 (repo-ast health는 jar 상태도 함께 반환 — E6 검증 겸용) |
| E4 | **JDK 21+** (jar 빌드·JDT LS 구동 공통 필수) | `java -version` ≥ 21 | assist | AskUserQuestion으로 설치/`JAVA_HOME` 지정 안내(sdkman/brew). 미충족이면 중단 | 하드 중단 + remediation | jar/E6, JDT LS/E7 |
| E5 | **Maven 3.6.3+** (jar 빌드용, 선택적) | `mcp/javaparser-cli/mvnw`(Windows `mvnw.cmd`) 존재 또는 `mvn -version` ≥ 3.6.3 | auto | mvnw 동봉으로 시스템 Maven 불필요(있으면 사용 가능). mvnw도 시스템 Maven도 없으면 설치 안내 | mvnw 사용, 둘 다 없으면 중단(빌드 불가) | E6 |
| E6 | **JavaParser CLI jar** (필수) | `REPO_AST_JAVAPARSER_JAR` 또는 `mcp/javaparser-cli/target/*-shaded.jar` 존재 | auto | `AskUserQuestion`: "예 — jar 빌드(`./mvnw package`)" / "아니오 — 중단" (정규식 degrade 선택지 없음) → 예: `(cd mcp/javaparser-cli && ./mvnw -q -DskipTests package)` → `target/astcli-1.0.0-shaded.jar` | **자동** 동일 명령 빌드, 실패 시 하드 중단(`JAVAPARSER_REQUIRED`) | policy #2 (필수; `.mcp.json`이 `REPO_AST_REQUIRE_JAVAPARSER=1` 기본 설정) |
| E7 | **JDT LS + Java 21+ 런타임** (필수) | `jdtls`(PATH) + `.lsp.json` + Java 21+ on `JAVA_HOME`/PATH | auto | 세팅: `node ${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs script ${CLAUDE_PLUGIN_ROOT}/scripts/setup_jdtls.py`. 실패(Java 21 미탐지 포함) 시 중단 | 동일 세팅 자동 수행, 실패 시 하드 중단(AST-only degrade 문구 없음) | policy #3 |
| E8 | **빌드 도구**(gradle/maven) | `build-test-mcp.detect_build_tool(root)` | data | `BUILD_TOOL_UNDETECTED`면 `AskUserQuestion("gradle? maven?")` | 미감지면 중단(`HarnessRequest.buildTool` 명시 요청) | policy #5 |
| E9 | **Spring Boot 버전/프로파일** | `build-test-mcp.detect_spring_profile(root)` | data | `interviewRequired`면 Boot major AskUserQuestion(#4); `requiresConfirmation`면 충돌 확정(#6). 가정 금지 | 미감지/충돌이면 중단(`HarnessRequest.springVersion` 명시) | policy #4·#6 |
| E10 | **테스트 실행 JDK ↔ Mockito 호환** | 실행 JDK major vs Mockito/ByteBuddy 지원 범위 | assist | JDK 24/25에서 inline mock-maker 미지원 위험이면 `AskUserQuestion`: "① 테스트 실행 JDK를 17/21 LTS로 / ② Mockito 5.16+(ByteBuddy 1.17+)로 / ③ `-Dnet.bytebuddy.experimental=true`" | 위험이면 자동 보정 불가 → 중단(remediation 안내) | RESEARCH_NOTES §5, ByteBuddy |
| E11 | **대상 빌드 능력**(JaCoCo XML 필수·PITest opt-in) | `build-test.detect_build_capabilities(root, junitEngine, require_pitest=mutation.enabled)` → `missing[]` | data(approve→inject) | JaCoCo 누락은 별도 승인 주입. PITest는 `enabled:true`일 때만 플러그인·JUnit 어댑터·XML을 검사/제안하며 거부 시 `enabled:false`로 전환해 9단계만 skipped | 자동 주입 금지. JaCoCo 또는 명시 활성화된 PITest 능력 누락만 remediation 중단; 기본 `enabled:false`에서는 PITest 누락 허용 | policy #17, [build-provisioning.md](./build-provisioning.md) §1 |
| E12 | **의존성 캐시 프라이밍**(콜드 캐시 첫 실행) | `build-test.check_dependency_cache(buildTool, root)` → `primed` | data(approve→prime) | `primed:false`/신규 플러그인이면 `AskUserQuestion("1회 온라인 프라이밍?")` → 예: `run_targeted_tests(online=True)` 1회(또는 Maven `dependency:go-offline`)→이후 오프라인 | 자동 온라인 금지 → `BUILD_TEST_ALLOW_NETWORK=1` 옵트인·사전 워밍업 안내 | policy #18, [build-provisioning.md](./build-provisioning.md) §2 |

E8·E9·E10·E11·E12는 **데이터 감지**라 "자동 빌드"로는 못 고친다 — 대화형은 질문(E11·E12는 승인 후 함께 세팅), CI는 필수 값·캐시를 사전 준비한다. 단, `mutation.enabled`는 선택 필드라 미지정 시 `false`이며 PITest 누락으로 중단하지 않는다. E11·E12는 **0.5단계(프로파일 확정) 직후 0.6단계에서 6단계 run-tests 이전에** 처리한다 — JaCoCo 에이전트는 `test` 실행 중 attach되므로 빌드 능력이 먼저 갖춰져야 한다.

---

## 세팅 명령 레퍼런스 (사실 확인됨)

```bash
# E1+E2: Python + MCP Python SDK — v0.15.0+ 자동(권장, 전 OS): Python이 없으면 uv로 설치 후 venv 준비
node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" --ensure-only        # E1(uv 관리형 Python, 무-sudo) + E2(${CLAUDE_PLUGIN_DATA}/venv에 mcp[cli]>=1.2.0)
#   (POSIX 전용 구진입점: sh "${CLAUDE_PLUGIN_ROOT}/mcp/run-server.sh" --ensure-only — 수동 폴백으로 유지)
#   수동 폴백(오프라인/venv 불가 환경): Python 3.10+ 설치 후 .mcp.json이 실행하는 동일 인터프리터에
python3 -m pip install -r mcp/requirements.txt          # (which python3 로 인터프리터 확인)

# E3b: MCP 라이브 연결 검증 — 세 서버의 health 도구를 실제 호출해 응답을 확인한다
#   (repo-ast-mcp.health / spec-doc-mcp.health / build-test-mcp.health)
#   실패 시 수동 점검: node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" --ensure-only 재실행 → /reload-plugins 또는 재시작

# E6: JavaParser CLI jar — mvnw 동봉(시스템 Maven 불필요), JDK 21+ 필요
cd mcp/javaparser-cli && ./mvnw -q -DskipTests package   # Windows: mvnw.cmd -q -DskipTests package
#   산출물: target/astcli-1.0.0-shaded.jar
#   오프라인 대안: 사전 빌드한 jar를 REPO_AST_JAVAPARSER_JAR="/abs/path/astcli-1.0.0-shaded.jar" 로 지정

# E7: JDT LS — jdtls 실행 파일 + Java 21+ 런타임 필요, 자동 설치 스크립트 제공
node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" script "${CLAUDE_PLUGIN_ROOT}/scripts/setup_jdtls.py"
#   PATH → brew(macOS) → eclipse.org milestone tarball(${CLAUDE_PLUGIN_DATA}/jdtls) 순으로 프로비저닝
#   (Eclipse JDT LS는 구동에 Java 21+ 요구, 컴파일 대상은 1.8–25 지원)
#   오프라인 대안: jdtls를 사전 설치해 PATH에 두거나 ${CLAUDE_PLUGIN_DATA}/jdtls에 미리 배치

# E10: 테스트 실행 JDK
#   JDK 17/21 LTS = inline mock-maker 완전 지원(권장)
#   JDK 24/25 = Mockito 5.16+(ByteBuddy 1.17+) 또는 -Dnet.bytebuddy.experimental=true 필요
```

> **첫 세팅 1회 네트워크 필요**: uv Python 설치, Maven 의존성 해석(mvnw 최초 실행 시 wrapper 배포판 다운로드 포함), JDT LS tarball 다운로드는 모두 최초 1회만 온라인이 필요하고 이후에는 로컬 캐시로 동작한다. 완전 오프라인 환경에서는 위 오프라인 대안(사전 빌드 jar 지정, jdtls 사전 설치)을 사용한다.

근거: `mcp/requirements.txt`·`mcp/javaparser-cli/README.md`·`.lsp.json`(저장소), Eclipse JDT LS Java 21 런타임 요구(2025-03 SDK 4.35), Mockito/ByteBuddy Java 25 class-file 69 미지원(Mockito ≤5.13).

---

## E-verify 검증 프로브 (파이프라인 시작 게이트) — 수행 주체: `configure-harness` / `full-pipeline`

`configure-harness`와 `full-pipeline`은 **세팅을 수행하지 않는다.** 시작 시 아래 프로브만 실행해 `setup-harness`가 이미 환경을 갖춰 놓았는지 **물리적으로 확인**한다. 전부 빠르고(밀리초~1초) 부작용이 없으며 멱등하다.

> **왜 "세팅 완료 파일"을 두지 않는가**: `_workspace/`는 휘발성(`.gitignore`)이고, 세팅 완료 리포트 파일은 모든 방향으로 stale 해질 수 있다(JDK 제거, `mvn clean`, 플러그인 업데이트로 venv 경로 변경). 무엇보다 **MCP 등록은 세션 단위**라 파일로는 E3b를 증명할 수 없다 — `health`를 실제 호출하는 것만이 유일하게 정직한 검증이다. 따라서 **증거는 파일이 아니라 프로브다.**

| 프로브 | 커버 항목 | 판정 |
|---|---|---|
| `repo-ast.health()` · `spec-doc.health()` · `build-test.health()` **3종 실제 호출** | **E3b**(라이브 연결) + 전이적으로 **E1·E2·E3**(런타임·venv·서버 등록이 없으면 애초에 응답 불가) | 도구 미노출/호출 실패 → 실패. repo-ast 응답의 `javaparser.jarFound:false` → E6 실패로 간주 |
| `java -version` ≥ 21 | **E4** | 미충족 → 실패 |
| `mcp/javaparser-cli/target/*-shaded.jar` 존재 또는 `REPO_AST_JAVAPARSER_JAR` 설정 | **E5·E6** | 미충족 → 실패 (위 health의 `jarFound`로 갈음 가능) |
| `node "${CLAUDE_PLUGIN_ROOT}/mcp/launch.cjs" script "${CLAUDE_PLUGIN_ROOT}/scripts/setup_jdtls.py" --check-only` | **E7** | 종료코드 ≠ 0 → 실패 (`--check-only`는 감지만 하고 설치하지 않는다) |
| 실행 JDK major ↔ Mockito/ByteBuddy 지원 범위 | **E10** | 위험이면 실패(또는 명시적 사용자 확인) |

**하나라도 실패하면** 대화형·CI 동일하게 `status:"failed"` + `errors`에 실패 항목을 담고 **파이프라인을 시작하지 않는다.** 이때 remediation은 항상 아래 **고정 안내 문자열**을 포함한다:

```
먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요
```

**금지**: 프로브 실패를 스스로 고치려 들지 않는다(`--ensure-only`·`./mvnw package`·`setup_jdtls.py` 세팅 실행 금지 — 그건 `setup-harness`의 일이다). 정규식·AST-only degrade로 우회하지도 않는다.

상태줄(S1)은 **게이트에 포함하지 않는다** — consent 기반 선택 기능이라 미설치가 파이프라인 실패 사유가 될 수 없다.

---

## 비대화형/CI 자동 세팅 흐름 (`setup-harness` 내부)

```
# setup-harness — 세팅 수행 주체
for item in [E2, E6, E7, ...결정적]:              # 런타임/필수 세팅(MCP SDK, JavaParser jar, JDT LS 등)
    if not detect(item):
        run(auto_fix_command)        # pip install / ./mvnw package / setup_jdtls.py
        if not detect(item):         # 재검증
            return failed(item, remediation)   # 자동 세팅 실패 → 하드 중단
for item in [E1, E4, E10]:                       # 비결정적/시스템 필수(JDK 21+ 포함)
    if not detect(item):
        return failed(item, remediation)        # 질문 불가 → 중단(설치 안내)
verify_mcp_health(E3b)                # repo-ast/spec-doc/build-test health 3종 호출, 실패 시 즉시 중단
```

대화형은 위 `run(auto_fix_command)`를 **AskUserQuestion 확인 후** 실행하고, 비결정적 항목은 **질문**으로 채운다.
(E8·E9는 configure-harness 0.5단계의 데이터 감지 항목이라 이 루프에 없다.)

```
# configure-harness / full-pipeline — 검증 전용(verify-only). 세팅하지 않는다.
if not e_verify_probes():                       # 위 「E-verify 검증 프로브」 표
    return failed(errors, "먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요")
```

---

## 통과 기준

- **`setup-harness` 완료 기준**: **E1·E2·E3·E3b·E4·E5(동봉 mvnw)·E6·E7·E10 전부 통과**. 하나라도 미충족이면 `status:"failed"` + remediation. (상태줄 S1은 선택 — 실패해도 `warnings`.)
- **파이프라인(`full-pipeline`/`configure-harness`) 시작 기준**: **E-verify 프로브 전부 통과**. 미통과 시 `status:"failed"` + 위 고정 안내 문자열로 **미시작 하드 중단**(자동 세팅 금지, 정규식·AST-only degrade 금지).
- **E8·E9(빌드도구·프로파일)**는 configure-harness **0.5단계**에서 확정한다(데이터 감지).
- **E11(빌드 능력)·E12(캐시 프라이밍)**는 0.5단계 직후 **0.6단계**에서 처리한다(6단계 run-tests 이전 필수). 대화형=승인 후 주입/프라이밍, CI=JaCoCo 또는 명시 활성화된 PITest 능력 미비 시 remediation 중단.
