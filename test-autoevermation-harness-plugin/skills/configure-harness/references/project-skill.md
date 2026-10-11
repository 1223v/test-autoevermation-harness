# 사용자가 요청한 프로젝트 스킬 저장

저장 요청이 있을 때만 읽는다. 자동 질문하지 않는다. Claude는 .claude/skills, Codex는 .agents/skills 아래에 저장한다. 플러그인 캐시·전역 설정에 저장하지 않는다.

#### 도메인 스킬 네이밍 규칙

- 네임스페이스: `/<skill-name>`
- 파일 위치: `<projectRoot>/.claude/skills/<skill-name>/SKILL.md`
- frontmatter: `name`, `description` 필드만 포함 (plugin 제약 준수)
- 본문: 현재 `HarnessConfig`를 기본 입력으로 포함하는 호출 절차

생성 예시 (`<projectRoot>/.claude/skills/validate-order-domain/SKILL.md`):

```markdown
---
name: validate-order-domain
description: 주문 도메인 특화 테스트 생성 및 커버리지 검증을 실행한다. "주문 도메인 테스트", "order 검증"처럼 주문 관련 테스트가 필요한 상황에서 자동 호출된다.
---

## 목적

주문 도메인(`com.example.order`)에 특화된 테스트 생성 파이프라인을 실행한다.
이 스킬은 `/test-autoevermation-harness-plugin:full-pipeline`을 아래 HarnessConfig로 호출한다.

## 저장된 HarnessConfig

(configure-harness가 생성한 HarnessConfig JSON 삽입)

## 실행

/test-autoevermation-harness-plugin:full-pipeline 을 위 HarnessConfig로 호출한다.
```

---
