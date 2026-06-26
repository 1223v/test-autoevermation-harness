package com.example.orders.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

import com.example.orders.application.dto.OrderDetailDto;
import com.example.orders.domain.Order;
import java.math.BigDecimal;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * 하네스 생성물(순수 단위, jupiter + MockitoExtension). 분기·경계값 커버.
 * scenarioRef: SC-SVC-001..004
 */
@ExtendWith(MockitoExtension.class)
class OrderQueryServiceTest {

  @Mock private OrderRepository orderRepository;

  @InjectMocks private OrderQueryService service;

  @ParameterizedTest
  @CsvSource({
    "40000,1,40000", // <50000, 홀수 고객 → 0% 할인
    "50000,1,47500", // >=50000 → 5%
    "100000,1,90000", // >=100000 → 10%
    "100000,2,88000", // 10% + VIP(짝수 id) 2% = 12%
  })
  @DisplayName("할인 분기 - 금액/고객등급 경계값")
  void applyDiscount_boundaries(long amount, long customerId, long expected) {
    BigDecimal result = service.applyDiscount(BigDecimal.valueOf(amount), customerId);
    assertThat(result).isEqualByComparingTo(BigDecimal.valueOf(expected));
  }

  @Test
  @DisplayName("금액이 0 이하 - IllegalArgumentException")
  void applyDiscount_nonPositive_throws() {
    assertThatThrownBy(() -> service.applyDiscount(BigDecimal.ZERO, 1L))
        .isInstanceOf(IllegalArgumentException.class);
  }

  @Test
  @DisplayName("주문 상세 조회 - 미존재 시 OrderNotFoundException")
  void getOrderDetail_missing_throws() {
    when(orderRepository.findById(7L)).thenReturn(null);
    assertThatThrownBy(() -> service.getOrderDetail(7L))
        .isInstanceOf(OrderNotFoundException.class);
  }

  @Test
  @DisplayName("주문 상세 조회 - 할인 적용된 dto 반환")
  void getOrderDetail_found_returnsDiscountedDto() {
    when(orderRepository.findById(1L))
        .thenReturn(new Order(1L, 2L, new BigDecimal("100000"), "CONFIRMED"));

    OrderDetailDto dto = service.getOrderDetail(1L);

    assertThat(dto.getId()).isEqualTo(1L);
    assertThat(dto.getFinalAmount()).isEqualByComparingTo(new BigDecimal("88000"));
    assertThat(dto.getStatus()).isEqualTo("CONFIRMED");
  }
}
