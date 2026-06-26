package com.example.order;

// Spring Boot 2.0 – 2.1 (최소 사양) 프로파일: JUnit 4 + @MockBean.
// JUnit4 필수 요소: @RunWith(SpringRunner.class), org.junit.Test, public class/메서드,
// @DisplayName 없음(서술적 메서드명으로 의도 표현). 매트릭스: RESEARCH_NOTES §8 / version-compatibility.md §2-C.

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Collections;
import java.util.List;
import org.junit.Test; // ← JUnit 4
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.junit4.SpringRunner; // ← JUnit4 러너
import org.springframework.test.web.servlet.MockMvc;

/**
 * @WebMvcTest slice (Boot 2.0/2.1, JUnit 4): OrderController 계층만 로드.
 *
 * <p>scenarioRef: SC-001, SC-002 / criteriaRef: AC-ORDER-001
 */
@RunWith(SpringRunner.class) // ← JUnit4에서 @WebMvcTest와 함께 필수
@WebMvcTest(OrderController.class)
public class OrderControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockBean private OrderQueryService orderQueryService;

  @Test
  public void listActiveOrders_singleOrder_returnsOkJsonWithOneElement() throws Exception {
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
  public void listActiveOrders_noOrders_returnsEmptyArrayAndOk() throws Exception {
    // scenarioRef: SC-002
    given(orderQueryService.findActiveOrders()).willReturn(Collections.emptyList());

    mockMvc
        .perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders.length()").value(0));
  }
}
