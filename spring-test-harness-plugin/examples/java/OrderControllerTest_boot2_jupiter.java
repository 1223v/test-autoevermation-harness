package com.example.order;

// Spring Boot 2.2 – 2.7 프로파일: JUnit 5(Jupiter) + @MockBean (구 boot.test.mock.mockito).
// 네임스페이스는 javax.* (Boot 2.x). 매트릭스: RESEARCH_NOTES §8 / version-compatibility.md §2-B.
// @MockitoBean(jakarta/3.4+/4.x) 버전은 examples/java/OrderControllerTest.java 참조.

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean; // ← Boot 2.x: @MockBean
import org.springframework.test.web.servlet.MockMvc;

/**
 * @WebMvcTest slice (Boot 2.x): OrderController 계층만 로드, OrderQueryService를 @MockBean으로 대체.
 *
 * <p>scenarioRef: SC-001, SC-002 / criteriaRef: AC-ORDER-001
 */
@WebMvcTest(OrderController.class)
class OrderControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockBean private OrderQueryService orderQueryService;

  @Test
  @DisplayName("활성 주문 단건 조회 - JSON 구조를 준수한다")
  void listActiveOrders_singleOrder_returnsCorrectJsonStructure() throws Exception {
    // scenarioRef: SC-001
    given(orderQueryService.findActiveOrders())
        .willReturn(List.of(OrderFixtures.confirmedOrder(1L)));

    mockMvc
        .perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders").isArray())
        .andExpect(jsonPath("$.orders.length()").value(1))
        .andExpect(jsonPath("$.orders[0].id").value(1));
  }

  @Test
  @DisplayName("활성 주문이 없을 때 - 빈 배열과 200 OK를 반환한다")
  void listActiveOrders_noOrders_returnsEmptyArray() throws Exception {
    // scenarioRef: SC-002
    given(orderQueryService.findActiveOrders()).willReturn(List.of());

    mockMvc
        .perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders.length()").value(0));
  }
}
