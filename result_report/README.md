# result_report — 설계·검증 산출물 아카이브

`spring-test-harness` 플러그인 **개발 과정의 보고서·근거·검증 자료**를 배포물(플러그인)과 분리해 보관하는 폴더다.
런타임에는 필요 없으며, 설계 의도와 검증 증거를 추적하기 위한 기록이다.

실제 배포 대상 플러그인은 상위 폴더의 [`../spring-test-harness-plugin/`](../spring-test-harness-plugin/)에 있다.

---

## 구성

```
result_report/
├── README.md              ← (이 파일) 아카이브 인덱스
└── docs/                  ← 설계 보고서 · 원칙 감사 · 검증 기록
    ├── REPORT.md              전체 설계 보고서(아키텍처·에이전트 스키마·권한 모델·JUnit 충돌 분석)
    ├── PRINCIPLES_AUDIT.md    revfactory/harness 설계 원칙 준수 감사 (#1~#16)
    └── VERIFICATION.md        라이브 검증 증거(MCP stdio 핸드셰이크·도구 호출·회귀 스냅샷 결과)
```

> **검증 스캐폴딩 제거(2026-07-01).** 개발 중 하네스를 검증하는 데 쓰던 재현 스크립트(`verification/*.py`)와
> 샘플 Spring 프로젝트(`sample-spring-app/`, `sample-spring-boot2/`, `sample-custom-components/`)는
> 하네스 런타임이 호출하지 않는 **개발 전용 자산**이라 최종 회귀 검증 후 제거했다.
> 검증 결과 자체는 [`docs/VERIFICATION.md`](docs/VERIFICATION.md)에 증거로 보존된다.

---

## 검증 재현 방법

검증에 쓰인 MCP stdio 핸드셰이크·버전 프로파일 감지·커스텀 컴포넌트 분류의 절차와 결과는
[`docs/VERIFICATION.md`](docs/VERIFICATION.md)(§1~§5)에 상세히 기록되어 있다. 재현이 필요하면
그 절차대로 샘플 프로젝트와 드라이런 스크립트를 재작성하고, 일회용 venv에 MCP SDK를 설치해 실행한다.

```bash
python3 -m venv /tmp/mcp-venv
/tmp/mcp-venv/bin/pip install -r ../spring-test-harness-plugin/mcp/requirements.txt
# (선택) JavaParser AST 백엔드: ( cd ../spring-test-harness-plugin/mcp/javaparser-cli && mvn -q -DskipTests package )
```
