# result_report — 설계·검증 산출물 아카이브

`spring-test-harness` 플러그인 **개발 과정의 보고서·근거·검증 자료**를 배포물(플러그인)과 분리해 보관하는 폴더다.
런타임에는 필요 없으며, 설계 의도와 검증 증거를 추적하기 위한 기록이다.

실제 배포 대상 플러그인은 상위 폴더의 [`../spring-test-harness-plugin/`](../spring-test-harness-plugin/)에 있다.

---

## 구성

```
result_report/
├── README.md              ← (이 파일) 아카이브 인덱스
├── docs/                  ← 설계 보고서 · 원칙 감사 · 검증 기록
│   ├── REPORT.md              전체 설계 보고서(아키텍처·에이전트 스키마·권한 모델·JUnit 충돌 분석)
│   ├── PRINCIPLES_AUDIT.md    revfactory/harness 설계 원칙 준수 감사 (#1~#16)
│   └── VERIFICATION.md        라이브 검증 증거(MCP stdio 핸드셰이크·도구 호출 결과)
├── verification/          ← 검증 재현 스크립트 (MCP 클라이언트)
│   ├── verify_stdio.py        3개 MCP 서버 stdio 핸드셰이크(initialize + tools/list) 점검
│   └── dryrun_sample.py       sample 앱 대상 extract_test_targets/detect_build_tool 등 도구 실호출
└── sample-spring-app/     ← 드라이런용 Spring Boot 4.1.0 샘플 (OrderController/OrderQueryService 등)
```

---

## 검증 스크립트 재현 방법

스크립트는 경로를 자동 해석한다 — 플러그인은 `../../spring-test-harness-plugin`, 샘플 앱은 `../sample-spring-app`.
실행에는 MCP Python SDK(`mcp[cli]`)가 필요하다.

```bash
# 1) 일회용 venv 생성 + MCP SDK 설치
python3 -m venv /tmp/mcp-venv
/tmp/mcp-venv/bin/pip install -r ../spring-test-harness-plugin/mcp/requirements.txt

# 2) (선택) JavaParser AST 백엔드 빌드 — 없으면 정규식 fallback
( cd ../spring-test-harness-plugin/mcp/javaparser-cli && mvn -q -DskipTests package )

# 3) 검증 실행 (result_report/ 기준)
/tmp/mcp-venv/bin/python verification/verify_stdio.py
/tmp/mcp-venv/bin/python verification/dryrun_sample.py
```

> 개발 당시 사용한 `.mcp-venv/`·빌드 산출물은 캐시 정리 시 제거되었으므로 위 1~2단계로 재생성한다.
> 검증 결과 요약은 [`docs/VERIFICATION.md`](docs/VERIFICATION.md)에 기록되어 있다.
