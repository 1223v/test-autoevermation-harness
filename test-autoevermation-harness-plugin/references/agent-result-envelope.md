# 에이전트 공통 결과 봉투 (SSOT)

11개 서브에이전트의 결과 JSON이 공유하는 공통 필드의 단일 정의다. 각 에이전트 문서는 이 표를 복사하지 않고 1줄로 참조한다(사본 drift 방지). 각 에이전트의 JSON 출력 스키마에는 이 필드들이 그대로 포함된다(스키마는 완결형 유지).

| 필드 | 타입 | 값 |
|---|---|---|
| `status` | enum | `ok` / `partial` / `failed` |
| `summary` | string | 1-3문장 요약 |
| `evidence` | string[] | 결론 근거 — 무엇을 담는지는 에이전트별 문서에 1줄로 명시 |
| `warnings` | any[] | 비치명적 이상 상황 |
| `errors` | any[] | 치명적 실패 상세 |
| `nextActions` | any[] | 후속 에이전트/사용자 권고 |

규약:
- `status: partial`은 "일부 산출 + 잔여를 `warnings`/특화 필드에 전량 보고"를 의미한다(임의 제외·침묵 누락 금지 — fallback-policy 공통 규칙 4).
- `status: failed`는 `errors`에 원인 코드와 remediation을 반드시 동반한다.
- `evidence`에 소스 코드 원문·민감정보를 담지 않는다(경로·라인·심볼·수치만).

## 도구 경계

- 하위 에이전트는 사용자에게 직접 질문하지 않는다. 필요한 결정은 `status:"failed"`, `errors`의 원인 코드, `nextActions`의 질문 주제·선택지로 반환하고 메인 대화가 처리한다.
- 읽기 전용 에이전트는 완결된 결과 JSON을 반환한다. 호출자가 검증한 뒤 `_workspace/`에 Write한다. 존재하지 않는 산출물 경로를 반환하지 않는다.
- 지원 도구는 실제 세션 목록과 frontmatter의 교집합이다. 지연 노출 MCP 도구는 메인 대화가 공식 ToolSearch로 먼저 찾아 활성화하고 위임한다. 도구가 없으면 이름을 지어 호출하지 않는다.
- 공식 제약: [sub-agents](https://code.claude.com/docs/en/sub-agents), [tools](https://code.claude.com/docs/en/tools-reference).
