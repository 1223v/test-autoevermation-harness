# 버전 호환 프로파일 — 전체 코드 템플릿 (Boot 2.0 – 4.x)

> 이 문서는 [RESEARCH_NOTES.md](../RESEARCH_NOTES.md) §8 매트릭스의 **실행 가능한 코드 템플릿**이다.
> 하네스는 `springProfile`을 감지/인터뷰로 확정한 뒤 아래 분기를 그대로 선택해 컴파일 가능한 코드를 생성한다.
> 모든 관용구는 공식 문서로 검증됨(§8 출처 참조).

`springProfile` 스키마:

```json
{
  "bootVersion": "2.7.18",       // 감지 best-effort, 미상이면 null
  "bootMajor": 2,                 // 2 | 3 | 4
  "namespace": "javax",           // "javax" (Boot 2.x) | "jakarta" (Boot 3.x+)
  "junitEngine": "jupiter",       // "junit4" | "jupiter"
  "mockAnnotation": "MockBean",   // "MockBean" (≤3.3) | "MockitoBean" (3.4+)
  "mockImport": "org.springframework.boot.test.mock.mockito.MockBean",
  "javaBaseline": 8,              // 8 (2.x) | 17 (3.x+)
  "gradleTestMode": "useJUnitPlatform",  // "useJUnit" | "useJUnitPlatform"
  "degraded": false               // 감지 신뢰도 낮음(인터뷰/가정으로 보강됨)
}
```

---

## 1. 네임스페이스 (javax ↔ jakarta)

| 용도 | Boot 2.x (`javax`) | Boot 3.x+ (`jakarta`) |
|---|---|---|
| JPA 엔티티 | `javax.persistence.Entity` | `jakarta.persistence.Entity` |
| Bean Validation | `javax.validation.constraints.NotNull` | `jakarta.validation.constraints.NotNull` |
| Servlet | `javax.servlet.http.HttpServletRequest` | `jakarta.servlet.http.HttpServletRequest` |
| `@PostConstruct` 등 | `javax.annotation.PostConstruct` | `jakarta.annotation.PostConstruct` |

생성 코드가 위 타입을 참조할 때는 **반드시 프로파일 네임스페이스로 import**한다. 대상 소스의 실제 import를 우선 따른다(혼용 프로젝트 방어).

---

## 2. 컨트롤러 슬라이스 — 프로파일별 전체 템플릿

### 2-A. Boot 4.x / 3.4+ (jupiter + @MockitoBean) — "latest"

```java
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(OrderController.class)
class OrderControllerTest {

  @Autowired private MockMvc mockMvc;
  @MockitoBean private OrderQueryService orderQueryService;

  @Test
  @DisplayName("활성 주문 단건 조회 — JSON 구조를 준수한다")
  void listActiveOrders_singleOrder() throws Exception {
    given(orderQueryService.findActiveOrders()).willReturn(java.util.List.of(/* ... */));
    mockMvc.perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders").isArray());
  }
}
```

### 2-B. Boot 2.2 – 3.3 (jupiter + @MockBean)

`@MockitoBean`을 `@MockBean`으로, import만 교체. **나머지는 2-A와 동일**(Jupiter, `@DisplayName` 유지).

```java
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;          // ← @MockBean
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(OrderController.class)
class OrderControllerTest {
  @Autowired private MockMvc mockMvc;
  @MockBean private OrderQueryService orderQueryService;            // ← @MockBean
  // @Test + @DisplayName 그대로 (Jupiter)
}
```

### 2-C. Boot 2.0 – 2.1 (junit4 + @MockBean) — 최소 사양

JUnit4: `@RunWith(SpringRunner.class)` 필수, `org.junit.Test`, **`@DisplayName` 없음**(메서드명으로 의도 표현), `public void` 메서드.

```java
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.Test;                                              // ← JUnit4
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.junit4.SpringRunner;        // ← SpringRunner
import org.springframework.test.web.servlet.MockMvc;

@RunWith(SpringRunner.class)                                        // ← 필수
@WebMvcTest(OrderController.class)
public class OrderControllerTest {

  @Autowired private MockMvc mockMvc;
  @MockBean private OrderQueryService orderQueryService;

  @Test
  public void listActiveOrders_singleOrder_returnsOkJson() throws Exception {
    given(orderQueryService.findActiveOrders()).willReturn(java.util.List.of(/* ... */));
    mockMvc.perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk());
  }
}
```

---

## 3. 서비스 / 순수 단위 테스트 — 프로파일별

| 축 | jupiter (2.2+/3.x/4.x) | junit4 (2.0–2.1) |
|---|---|---|
| 러너/확장 | `@ExtendWith(MockitoExtension.class)` | `@RunWith(MockitoJUnitRunner.class)` |
| 테스트 | `org.junit.jupiter.api.Test` + `@DisplayName` | `org.junit.Test` (public void) |
| Mock | `@Mock` / `Mockito.mock()` | `@Mock` / `Mockito.mock()` (동일) |
| Assert | AssertJ `assertThat` (권장, 공통) | AssertJ `assertThat` 또는 `org.junit.Assert` |
| 예외 | `assertThrows(...)` | `assertThrows(...)`(JUnit 4.13+) 또는 `@Test(expected=...)` |

> AssertJ·Mockito·BDDMockito는 모든 프로파일 공통(`spring-boot-starter-test`가 BOM으로 관리).

---

## 4. JPA 슬라이스 (`@DataJpaTest`)

모든 프로파일에서 애노테이션은 동일. 차이는 **엔티티 네임스페이스**(§1)와 JUnit 엔진(§2)뿐.
- junit4면 `@RunWith(SpringRunner.class)` 추가.
- 엔티티가 `javax.persistence`(2.x) / `jakarta.persistence`(3.x+)인지 대상 소스로 확인.

---

## 5. 빌드 설정 — 프로파일별

### 5-A. Gradle — jupiter (2.2+ / 3.x / 4.x)

```kotlin
tasks.named<Test>("test") { useJUnitPlatform() }
jacoco { toolVersion = "0.8.12" }
```

Boot 2.4+에서 JUnit4 테스트가 일부 남아 있으면 vintage 엔진을 명시 추가:

```kotlin
testImplementation("org.junit.vintage:junit-vintage-engine") { exclude(group = "org.hamcrest") }
```

### 5-B. Gradle — junit4 (2.0–2.1, 순수 JUnit4)

```groovy
// Boot 2.0/2.1: spring-boot-starter-test가 JUnit4를 가져온다. Platform 불필요.
test { useJUnit() }        // ← useJUnitPlatform() 아님
jacoco { toolVersion = '0.8.12' }   // Java 8 런타임 정상
java { sourceCompatibility = JavaVersion.VERSION_1_8 }
```

### 5-C. Maven — Java 베이스라인

```xml
<!-- Boot 2.x (Java 8): -->
<maven.compiler.release>8</maven.compiler.release>   <!-- 또는 source/target 1.8 -->
<!-- Boot 3.x+/4.x (Java 17): -->
<maven.compiler.release>17</maven.compiler.release>
```

Surefire는 JUnit Platform(2.22+)·JUnit4 모두 지원. JaCoCo 플러그인 `0.8.12` 동일.

---

## 6. 생성기 분기 의사코드

```text
profile = detect_spring_profile(root)              # 또는 인터뷰/가정
mock     = profile.mockAnnotation                  # MockBean | MockitoBean
mockImp  = profile.mockImport
ns       = profile.namespace                        # javax | jakarta  → 엔티티/검증/서블릿 import
if profile.junitEngine == "junit4":
    클래스에 @RunWith(SpringRunner.class) 부착(슬라이스/컨텍스트), 순수 단위는 @RunWith(MockitoJUnitRunner.class)
    import org.junit.Test;  메서드 public void;  @DisplayName 생략(메서드명으로 의도 표현)
    빌드: useJUnit()(2.0/2.1) 또는 vintage 의존성 안내
else:  # jupiter
    import org.junit.jupiter.api.Test + @DisplayName(한국어 행위 서술)
    순수 단위는 @ExtendWith(MockitoExtension.class)
    빌드: useJUnitPlatform()
컨트롤러 협력 빈 → @{mock}, import {mockImp}
```

생성 전 대상 소스의 **실제 import**(javax/jakarta)와 **기존 테스트의 JUnit 엔진**을 우선 확인해 프로파일과 충돌 시 대상 소스를 따른다(혼용 방어). 충돌은 `warnings`에 기록.
