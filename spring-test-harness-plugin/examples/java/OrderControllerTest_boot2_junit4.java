package com.example.order;

// Spring Boot 2.0 – 2.1 (최소 사양): JUnit 4 + @MockBean. @RunWith(SpringRunner.class) 필수,
// @DisplayName 없음 → scenarioRef 접두 + 서술적 메서드명으로 의도 표현. 본문은 BDD given/when/then.

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Collections;
import java.util.List;
import org.junit.Test; // JUnit 4
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

@RunWith(SpringRunner.class)
@WebMvcTest(OrderController.class)
public class OrderControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockBean private OrderQueryService orderQueryService;

  /** scenarioRef: SC-001 / criteriaRef: AC-ORDER-001 */
  @Test
  public void sc001_listActiveOrders_returnsOkJsonWithOneElement() throws Exception {
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
  public void sc002_listActiveOrders_returnsEmptyArrayAndOk() throws Exception {
    // given
    given(orderQueryService.findActiveOrders()).willReturn(Collections.emptyList());

    // when
    ResultActions result =
        mockMvc.perform(get("/api/orders/active").accept("application/json"));

    // then
    result.andExpect(status().isOk()).andExpect(jsonPath("$.orders.length()").value(0));
  }
}
