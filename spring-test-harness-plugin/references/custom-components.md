# 커스텀 컴포넌트 처리 (Custom Components) — SSOT

직접 만든 Spring 컴포넌트(커스텀 스테레오타입, 합성 매핑 애노테이션, 커스텀 인프라)에
대한 하네스의 인식·테스트 생성 규칙. `repo-ast-mcp`의 분류 로직과 에이전트 지시문이 이
문서를 단일 출처로 참조한다.

근거(공식문서):
- Classpath Scanning and Managed Components — *"@Component 메타 애노테이션이 붙은 모든
  애노테이션은 스테레오타입으로 간주되어 컴포넌트 스캔 대상이 된다"*, *"@Service, @Controller,
  @Repository는 @Component의 특수화(specialization)"*.
- Composed @RequestMapping Variants / `@AliasFor` — `@GetMapping` 등은
  `@AliasFor(annotation = RequestMapping.class)`로 `@RequestMapping` 속성을 재정의하는
  합성 애노테이션이다. 커스텀 매핑 애노테이션도 동일 방식으로 path/method를 메타 애노테이션에
  위임한다.
- MergedAnnotations / AnnotatedElementUtils — 메타 애노테이션 관계는 **전이적(transitive)**.
  거리(distance) 2 이상의 메타 애노테이션도 인식된다.

---

## 1. 커스텀 스테레오타입 (meta-annotated stereotype)

`@interface UseCase`가 `@Component`(또는 `@Service`/`@Repository`/`@Controller`)로 메타
애노테이트되면, `@UseCase`가 붙은 클래스는 Spring 빈이다.

**하네스 동작**
- `repo-ast-mcp`는 분석 대상 파일군 전체에서 `@interface` 선언을 스캔해 메타 애노테이션을
  **전이적으로** 해석한다(`_build_meta_index`). 거리 2(`@ReadModel → @UseCase → @Component`)도
  올바르게 해석된다.
- 해석된 커스텀 스테레오타입이 붙은 클래스는 더 이상 `pojo`가 아니라 해당 `kind`
  (controller/service/repository/component)로 분류되고, `list_spring_components` 자동탐지에도
  포함된다.
- 여러 스테레오타입이 겹치면 더 구체적인 것이 우선한다(controller > repository > service >
  component).

**테스트 생성**
- 표준 스테레오타입과 동일하게 처리한다. 일반 비즈니스 컴포넌트(`@UseCase` 등)는 **순수 단위
  테스트**(Mockito + BDD G/W/T)로 생성한다. 협력 빈 대체는 `springProfile.mockAnnotation`을 따른다.

**한계**: 커스텀 애노테이션의 `@interface` 선언이 분석 경로(`REPO_AST_ALLOW_ROOT`) 밖(외부
라이브러리 jar)에 있으면 메타 애노테이션을 읽을 수 없어 `pojo`로 남는다. 이때는 `targets`에
FQCN을 명시하면 pojo 단위 테스트는 생성된다.

## 2. 합성 매핑 애노테이션 (composed @RequestMapping)

`@GetJson`처럼 `@RequestMapping`/`@GetMapping`을 메타로 갖고 path를 `@AliasFor`로 재정의하는
커스텀 매핑 애노테이션. URL path·HTTP method가 **애노테이션 이름 위에 드러나지 않는다**.

**하네스 동작**
- `repo-ast-mcp`는 합성 매핑 애노테이션을 전이적으로 식별해, 해당 엔드포인트에 대해
  `riskPoints`에 경고를 남긴다:
  `"<Controller>#<method>: composed mapping @X detected; confirm URL path/HTTP method
  (@AliasFor override) before building the MockMvc request"`.
- 클래스 자체는 `@RestController`/`@Controller`이므로 controller로 정상 분류되고, 메서드도
  엔드포인트로 감지된다(파라미터 애노테이션이 있어도).

**테스트 생성 (필수 보정)**
- 합성 매핑 riskPoint가 있는 컨트롤러는 MockMvc 요청을 만들기 전에 **path와 HTTP method를
  반드시 확인**한다. 확인 출처(우선순위): ① 커스텀 매핑 `@interface`의 메타 `@RequestMapping`
  속성과 `@AliasFor` 매핑 → ② 사용처의 애노테이션 인자(`@GetJson("/orders/{id}")`) →
  ③ 불명확하면 `warnings`에 기록하고 시나리오의 명시 경로를 사용.
- HTTP method는 메타 애노테이션의 `method`/변형 종류(GetMapping=GET 등)에서 결정한다.

## 3. 커스텀 인프라 컴포넌트 (validator / converter / interceptor / resolver)

스테레오타입 없는 평범한 클래스(`ConstraintValidator`, `Converter`,
`HandlerInterceptor`, `HandlerMethodArgumentResolver` 등).

**하네스 동작**
- 스테레오타입이 없으므로 `pojo`로 분류되지만, `extract_test_targets`는 kinds 필터가 없으면
  pojo도 타깃에 포함하므로 **테스트 대상에서 누락되지 않는다**.

**테스트 생성**
- 인터페이스 계약 메서드를 **순수 단위 테스트**한다.
  - `ConstraintValidator<A,T>` → `isValid(value, context)`를 직접 호출. null/경계/정상/위반 등치류로
    파라미터화. `ConstraintValidatorContext`는 Mockito mock으로 주입.
  - `Converter<S,T>` → `convert(source)` 정상/예외 케이스.
  - `HandlerInterceptor` → `preHandle/postHandle` 반환값·부수효과.
- Spring 컨텍스트 로딩 불필요(슬라이스 금지). 이렇게 하면 빠르고 결정적이다.

---

## 분류 결과 요약

| 커스텀 컴포넌트 유형 | 분류 | 자동탐지 | 테스트 전략 |
|---|---|---|---|
| `@UseCase`(meta `@Component`) | component(또는 specialization) | 포함 | 순수 단위(Mockito) |
| `@ReadModel`(거리 2 전이) | component | 포함 | 순수 단위(Mockito) |
| `@GetJson`(meta `@RequestMapping`) 컨트롤러 | controller | 포함 | `@WebMvcTest`+MockMvc, **path/method 확인 후** |
| 커스텀 validator/converter 등 | pojo | (kinds 미지정 시) 포함 | 순수 단위 |
