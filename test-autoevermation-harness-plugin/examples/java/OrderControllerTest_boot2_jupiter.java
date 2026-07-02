package com.example.order;

// Spring Boot 2.2 – 2.7 프로파일: JUnit 5(Jupiter) + @MockBean. 네임스페이스 javax.*.
// 메서드명에 scenarioRef(sc001..) 포함, 본문은 BDD given/when/then 3단.

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean; // Boot 2.x: @MockBean
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

@WebMvcTest(OrderController.class)
class OrderControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockBean private OrderQueryService orderQueryService;

  /** scenarioRef: SC-001 / criteriaRef: AC-ORDER-001 */
  @Test
  @DisplayName("활성 주문 단건 조회 - 200과 JSON 구조를 준수한다")
  void sc001_listActiveOrders_returnsOkJsonStructure() throws Exception {
    // given
    given(orderQueryService.findActiveOrders())
        .willReturn(List.of(OrderFixtures.confirmedOrder(1L)));

    // when
    ResultActions result =
        mockMvc.perform(get("/api/orders/active").accept("application/json"));

    // then
    result
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders").isArray())
        .andExpect(jsonPath("$.orders.length()").value(1))
        .andExpect(jsonPath("$.orders[0].id").value(1));
  }

  /** scenarioRef: SC-002 / criteriaRef: AC-ORDER-001 */
  @Test
  @DisplayName("활성 주문이 없을 때 - 빈 배열과 200 OK를 반환한다")
  void sc002_listActiveOrders_returnsEmptyArray() throws Exception {
    // given
    given(orderQueryService.findActiveOrders()).willReturn(List.of());

    // when
    ResultActions result =
        mockMvc.perform(get("/api/orders/active").accept("application/json"));

    // then
    result.andExpect(status().isOk()).andExpect(jsonPath("$.orders.length()").value(0));
  }
}
