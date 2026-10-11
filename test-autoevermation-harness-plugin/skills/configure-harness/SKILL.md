---
name: configure-harness
description: Spring 테스트 하네스의 최초 설정이나 명시적인 대상·모드·임계값 변경 요청에서 HarnessConfig를 만든다. 저장된 설정과 실제 프로젝트 감지를 우선하고 누락·충돌 값만 묻는다. 단순 실행·측정·조회마다 설정 인터뷰를 반복하지 않는다.
---

## 실행 계약

현재 문맥에 없는 경우에만 [호스트 계약](../../references/host-runtime.md), 해당 호스트 문서,
[근거 중심 절차](../../references/evidence-workflow.md), [공용 실행 정책](../../references/execution-policy.md)을 읽는다.
질문은 메인 대화에서만 한다. 호스트별 실제 질문 도구를 사용하며 없으면 일반 대화로 응답을 기다린다.
가용성을 시험하는 질문은 하지 않는다. 거절·취소·무응답은 승인 부재이며 CI로 전환하지 않는다.
명시적 skipInterview:true 또는 입력 불가 호스트에서만 비대화형 정책을 적용한다.

## 1. 기존 설정과 입력 확인

- 유효한 schemaVersion:2 저장 설정, 사용자의 요청, 실제 작업공간과 빌드 파일을 읽는다.
- projectRoot는 사용자 지정/현재 단일 프로젝트에서 확인한 절대 경로다. 여러 후보면 질문한다. 플러그인 설치 cwd를 대상이라고 추정하지 않는다.
- targets(패키지/FQCN), targetModules(모듈 경로), specDocPaths, buildTool, springProfile을 구분한다.
- 실제 빌드 파일·소스·기존 테스트로 감지할 수 있는 값은 묻지 않는다. 대상 범위·버전 충돌·해결 불가능한 의미만 질문한다.
- 스펙이 명시되지 않았고 지정할 필요도 없으면 빈 목록과 source-based 경고를 사용한다. 발견된 문서를 사용자 의도 없이 전부 포함하지 않는다.
- 이전 승인·제외·모드 결정을 반복 확인하지 않는다. 사용자 요청이 실제로 바꾼 값만 갱신한다.

## 2. E-verify와 환경 준비

[environment-setup.md](../../references/environment-setup.md)의 호스트별 E-verify 프로브를 적용한다.
같은 세션·대상·환경에서 이미 검증했다면 재사용한다. 새 세션, 연결 실패, 런타임/설정 변경 시 다시 확인한다.
정상 초기 경로에서는 이 스킬이 수행하고 full-pipeline이 중복 실행하지 않는다.
설치 주체는 setup-harness다. configure-harness 내부에서 설치 명령을 복제하지 않는다.
누락 항목의 다운로드·변경 내용을 묶어 제시하고 동의가 있으면 setup-harness로 준비한 뒤 돌아온다.
동의 없는 자동 세팅·자동 위임 금지. 준비할 수 없으면 failed와 아래 안내를 반환한다:

`먼저 /test-autoevermation-harness-plugin:setup-harness 를 실행해 환경 세팅을 완료하세요`

Codex는 JavaParser Java 17+, Claude JDT LS는 Java 21+를 확인한다. 테스트 JVM은 별도다.
MCP·JavaParser 미가용을 정규식 파싱으로 대체하지 않는다. Codex에 JDT LS나 상태줄을 요구하지 않는다.

## 3. 버전·빌드 능력

`detect_build_tool(root=projectRoot)`, `detect_spring_profile(root=projectRoot,java_home=javaHome)`로 실제 값을 확인한다.
동일 빌드/소스 근거의 저장 감지는 재사용한다. degraded/interviewRequired/requiresConfirmation이면 누락·충돌 질문으로 묶는다.
정확한 Spring Boot 버전이 필요하며 최신 버전을 추정하지 않는다. 실제 지원 매트릭스는 [version-compatibility.md](../../references/version-compatibility.md).
CI 필수 값 부재는 INTERVIEW_REQUIRED, 버전 충돌은 PROFILE_CONFLICT로 중단한다.

생성 파이프라인은 첫 테스트 실행 전에 JaCoCo XML 능력을 확인한다:
- `detect_build_capabilities`: 누락한 proposedChanges만 제시하고 동의 후 최소 주입·재감지한다.
- `check_dependency_cache`: primed는 휴리스틱 신호이며 프로젝트 의존성 완비의 증거가 아니다.
- 콜드 캐시는 1회 온라인 실행 허용 여부를 환경·빌드 변경과 함께 묻는다. 승인 시 첫 실제 실행에 online:true를 사용하고 이후 오프라인으로 돌아간다. 별도 같은 테스트 프라이밍 실행을 덧붙이지 않는다.
- CI는 BUILD_TEST_ALLOW_NETWORK=1 등 기존 명시적 옵트인만 사용한다. 임의 온라인 전환하지 않는다.
- 결과를 00b_build_provision.json에 보존해 중복 주입하지 않는다. 세부 스니펫은 [build-provisioning.md](../../references/build-provisioning.md).

## 4. 필요한 질문만 묶기

확정된 값은 요약으로 알린다. 다음 중 실제로 미정인 항목만 한 질문 묶음으로 요청한다:
대상 선택, 해결되지 않은 버전 충돌, 최초 모드, 필요한 환경/빌드/다운로드 동의.
각 동의 항목의 영향은 구분하고 이미 허용한 항목을 다시 승인받지 않는다.

최초 모드 선택 예시(Claude 형식; Codex는 실제 도구 형식으로 변환):

```json
{
  "questions": [{
    "question": "테스트 생성의 검증 목표와 자동 보정 예산을 선택하세요. 이 프로젝트에 저장합니다.",
    "header": "실행 모드",
    "options": [
      {"label": "균형 (권장)", "description": "LINE 90 / BRANCH 80 / METHOD 90 / CLASS 100%, 총 보정 3회"},
      {"label": "빠름", "description": "80 / 70 / 80 / 100%, 총 보정 1회"},
      {"label": "엄격", "description": "95 / 90 / 95 / 100%, 기존 무진전 종료 규칙"}
    ],
    "multiSelect": false
  }]
}
```

직접 지정 임계값·제외 목록은 자유 입력으로 한 번에 받는다. 네 카운터를 하나씩 다시 묻지 않는다.
기존 config에 executionPolicy가 없으면 기존 임계값·반복 의미를 유지한다. 모드 변경을 강요하지 않는다.
비대화형 신규 설정에 모드가 없으면 기존 strict 기본값을 사용한다. 부족한 필수 대상/루트/버전을 임의 채우지는 않는다.

## 5. config 저장

확정된 request와 saved를 공용 `mcp/harness_policy.py resolve`에 JSON stdin으로 전달한다.
호스트의 launch.cjs script 경로를 사용한다. 출력이 실패면 저장하지 않는다.
선택 정책은 executionPolicy:{profile,maxAutoFixRounds,delegation:"auto"}다.
직접 입력 coverage가 모드 기본값보다 우선한다. 모드 변경 없이 저장된 custom coverage를 바꾸지 않는다.

HarnessConfig는 schemaVersion:2와 기존 필드를 유지한다:
projectRoot, specDocPaths, targets, targetModules, buildTool, junitPolicy, testScope, javaVersion,
springVersion, springProfile, stylePolicy, lspAvailable, maxRepairRetries, domainKeywords,
coverage{line,branch,method,class,excludes}, coverageMaxIterations, refactorAdvisory.
기존 기본값은 junitPolicy:jupiter-style, testScope:mixed, stylePolicy:google-java,
maxRepairRetries:3, coverageMaxIterations:3, refactorAdvisory:{enabled:true,thresholds:{cyclomatic:10,constructorArgs:7}}.
실제 확인된 host/analysisBackend/analysisContext/javaHome/reportDirs/coverageReportPaths/aggregateReport만 선택 저장한다.
Codex는 host:codex, analysisBackend:javaparser-source, lspAvailable:false다.
Claude lspAvailable:true는 실제 documentSymbol 연결 증거가 있을 때만 기록한다.
상대 보고서·소스 경로는 확정 root 기준이고 경계 이탈을 허용하지 않는다.
실행 인자 매핑은 [compatibility-runtime.md](../../references/compatibility-runtime.md)를 필요한 경우 읽는다.

`_workspace/00_config-harness.json`에 전체 JSON을 저장한다. execution-budget.json은 설정 저장/재개로 초기화하지 않는다.
사용자가 재사용 스킬 저장을 요청한 경우에만 [project-skill.md](references/project-skill.md)를 읽는다.
Claude: `<projectRoot>/.claude/skills/<name>/SKILL.md`, Codex: `<projectRoot>/.agents/skills/<name>/SKILL.md`.
플러그인 캐시·전역 에이전트 설정에는 저장하지 않는다. 이름 충돌 때만 확인한다.

## 출력·중단

실제 확정된 HarnessConfig와 짧은 설정 요약을 반환한다. 추가 계획 승인 단계는 없다.
환경 불가·필수 입력 누락·미해결 버전 충돌은 failed와 오류/대응을 반환한다.
시나리오 승인은 이 스킬이 대신하지 않는다. 무응답·취소·시간 경과를 승인으로 기록하지 않는다.

기존 반복 필드 기본값은 `"maxRepairRetries": 3`, coverageMaxIterations:3이며 엄격/기존의 무진전 추적 의미를 보존한다. 빌드 감지·동의는 기존 0.6단계다.
