# 생성 테스트 코드 불변식 (SSOT)

생성·수정되는 모든 테스트 코드(5단계 생성, 7단계 보정, 8단계 gap-closing, 활성화된 9단계 단언 강화, 10.5단계 적합성 보정)가 공통으로 지켜야 하는 불변식의 단일 출처다. 각 에이전트·스킬은 이 문서를 1줄로 참조하고 재서술하지 않는다(사본 drift 방지).

## 1. 금지 패턴 (도입·유지 모두 금지)

| 패턴 | 이유 |
|---|---|
| 실제 네트워크 호출 (`RestTemplate`/`WebClient` 직접 호출 등) | 비결정성·외부 의존. seam은 mock/stub으로 대체 |
| 고정 시간 지연: `Thread.sleep`, `TimeUnit.sleep`, Awaitility의 고정 `pollDelay(...)` | flaky 고착. **조건 기반 `Awaitility.await().until(...)` 폴링은 결정적 대기로 허용**(flaky 교정의 권장 수단) |
| broad catch: `catch (Exception e) {}` / `catch (Throwable t) {}` | 실패 은폐 |
| over-mock: 실제 호출되지 않는 메서드까지 `when/thenReturn` 선언 | 거짓 안정성·유지비 |
| trivially-satisfying assertion: `assertTrue(true)`, `assertNotNull(result)` 단독 | 뮤테이션 내성 없음 |
| `@Disabled`/단언 제거·완화로 통과시키기 | 문제 은폐. **단언은 강화만 허용, 완화 금지** |
| 프로덕션 소스(`src/main/`) 수정 | 테스트 계층의 권한 밖. 프로덕션 버그 확인 시 `warnings`+수동 요청 |

## 2. scenarioRef 보존 (10단계 매핑 의존)

- 시나리오 테스트 메서드명 `<scenarioRefSlug>_<행위>`(예: `sc001_...`)와 javadoc `scenarioRef`/`criteriaRef`는 **리네임·삭제·변경 금지**.
- 10단계 `verify-scenarios`가 이 매핑으로 시나리오↔테스트 적합성을 판정한다 — 깨지면 `missing` 오판.
- 새로 추가하는 비시나리오 테스트(예: mutant-killing, gap-closing 보강 메서드)는 scenarioRef가 필요 없다.

## 3. BDD 구조·stub 스타일

- 본문은 `// given → // when → // then` 3단 구조 보존(예외 검증은 `// when & then` 병합 허용). 시나리오 given/when/then 1:1 반영.
- stub은 `BDDMockito given().willReturn()/willThrow()` 스타일 유지 — `when().thenReturn()` 혼용 도입 금지.
- `// then` 단언은 시나리오 then을 빠짐없이 반영해야 한다(10단계 `thenCovered` 판정 의존).

## 4. 버전 프로파일 관용구

- `springProfile`(namespace javax/jakarta · junitEngine junit4/jupiter · mockAnnotation `@MockBean`/`@MockitoBean` + 정확한 import)을 따른다. 정본: [version-compatibility.md](./version-compatibility.md).
- `springProfile` 미전달 시 기존 테스트·대상 소스의 실제 import를 정본으로 판별(혼용 방어 규칙).

## 5. 스타일·픽스처

- Google Java Style, import 완결(와일드카드 금지), 매직값 금지(`<Type>Fixtures`/`<Type>Builder` 또는 명명 상수).
- `@DisplayName` 한국어 행위 서술은 jupiter 한정 — junit4는 서술적 메서드명으로 대체.
