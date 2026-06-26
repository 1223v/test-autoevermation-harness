package com.example.orders.web;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.orders.application.OrderNotFoundException;
import com.example.orders.application.OrderQueryService;
import com.example.orders.application.dto.OrderDetailDto;
import java.math.BigDecimal;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean; // Boot 2.x 프로파일: @MockBean
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/**
 * 하네스 생성물(Boot 2.x / jupiter / @MockBean). 메서드명에 scenarioRef 포함, 본문 BDD given/when/then.
 */
@WebMvcTest(OrderController.class)
class OrderControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockBean private OrderQueryService orderQueryService;

  /** scenarioRef: SC-001 / criteriaRef: AC-ORDER-001 */
  @Test
  @DisplayName("주문 단건 조회 - 200과 JSON 본문을 반환한다")
  void sc001_getOrder_returnsOkBody() throws Exception {
    // given
    given(orderQueryService.getOrderDetail(1L))
        .willReturn(new OrderDetailDto(1L, new BigDecimal("90000"), "CONFIRMED"));

    // when
    ResultActions result = mockMvc.perform(get("/api/orders/1").accept("application/json"));

    // then
    result
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.id").value(1))
        .andExpect(jsonPath("$.status").value("CONFIRMED"))
        .andExpect(jsonPath("$.finalAmount").value(90000));
  }

  /** scenarioRef: SC-002 / criteriaRef: AC-ORDER-003 */
  @Test
  @DisplayName("존재하지 않는 주문 - 404와 ORDER_NOT_FOUND를 반환한다")
  void sc002_getOrder_returns404() throws Exception {
    // given
    given(orderQueryService.getOrderDetail(999L))
        .willThrow(new OrderNotFoundException("Order 999 not found"));

    // when
    ResultActions result = mockMvc.perform(get("/api/orders/999").accept("application/json"));

    // then
    result.andExpect(status().isNotFound()).andExpect(content().string("ORDER_NOT_FOUND"));
  }
}
