package com.example.order;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.order.domain.Money;
import com.example.order.domain.Order;
import com.example.order.domain.OrderStatus;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

/**
 * @WebMvcTest slice: OrderController 계층만 로드. Spring Security 자동설정을 비활성화하고
 * OrderQueryService를 @MockitoBean으로 대체한다.
 *
 * <p>scenarioRef: SC-001(주문 목록 조회 - 정상), SC-002(주문 목록 조회 - 빈 결과)
 * criteriaRef: AC-ORDER-001
 */
@WebMvcTest(OrderController.class)
@TestPropertySource(
    properties = {
      "spring.security.enabled=false",
      "order.page-size-default=20",
    })
class OrderControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockitoBean private OrderQueryService orderQueryService;

  @Test
  @DisplayName("활성 주문 목록 조회 - 단건 응답이 JSON 구조를 준수한다")
  void listActiveOrders_singleOrder_returnsCorrectJsonStructure() throws Exception {
    // scenarioRef: SC-001
    Order order =
        Order.builder()
            .id(1L)
            .customerId(42L)
            .totalAmount(Money.of(new BigDecimal("15000"), "KRW"))
            .status(OrderStatus.CONFIRMED)
            .placedAt(Instant.parse("2026-06-01T09:00:00Z"))
            .build();

    given(orderQueryService.findActiveOrders()).willReturn(List.of(order));

    mockMvc
        .perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders").isArray())
        .andExpect(jsonPath("$.orders.length()").value(1))
        .andExpect(jsonPath("$.orders[0].id").value(1))
        .andExpect(jsonPath("$.orders[0].status").value("CONFIRMED"))
        .andExpect(jsonPath("$.orders[0].totalAmount.amount").value(15000))
        .andExpect(jsonPath("$.orders[0].totalAmount.currency").value("KRW"));
  }

  @Test
  @DisplayName("활성 주문이 없을 때 - 빈 배열과 200 OK를 반환한다")
  void listActiveOrders_noOrders_returnsEmptyArray() throws Exception {
    // scenarioRef: SC-002
    given(orderQueryService.findActiveOrders()).willReturn(List.of());

    mockMvc
        .perform(get("/api/orders/active").accept("application/json"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.orders").isArray())
        .andExpect(jsonPath("$.orders.length()").value(0));
  }

  @Test
  @DisplayName("존재하지 않는 주문 ID 조회 - 404 Not Found를 반환한다")
  void getOrderById_notFound_returns404() throws Exception {
    // scenarioRef: SC-003
    given(orderQueryService.findById(999L))
        .willThrow(new OrderNotFoundException("Order 999 not found"));

    mockMvc
        .perform(get("/api/orders/999").accept("application/json"))
        .andExpect(status().isNotFound())
        .andExpect(jsonPath("$.errorCode").value("ORDER_NOT_FOUND"));
  }
}
