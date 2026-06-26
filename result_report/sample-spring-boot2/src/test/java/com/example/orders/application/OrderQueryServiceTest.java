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
 * 하네스 생성물(순수 단위, jupiter + MockitoExtension). 메서드명에 scenarioRef, 본문 BDD given/when/then.
 */
@ExtendWith(MockitoExtension.class)
class OrderQueryServiceTest {

  @Mock private OrderRepository orderRepository;

  @InjectMocks private OrderQueryService service;

  /** scenarioRef: SC-003 / criteriaRef: AC-DISCOUNT-001 */
  @ParameterizedTest
  @CsvSource({
    "40000,1,40000", // <50000, 홀수 고객 → 0%
    "50000,1,47500", // >=50000 → 5%
    "100000,1,90000", // >=100000 → 10%
    "100000,2,88000", // 10% + VIP(짝수 id) 2% = 12%
  })
  @DisplayName("할인 분기 - 금액/고객등급 경계값")
  void sc003_applyDiscount_boundaries(long amount, long customerId, long expected) {
    // given
    BigDecimal input = BigDecimal.valueOf(amount);

    // when
    BigDecimal result = service.applyDiscount(input, customerId);

    // then
    assertThat(result).isEqualByComparingTo(BigDecimal.valueOf(expected));
  }

  /** scenarioRef: SC-004 / criteriaRef: AC-DISCOUNT-002 */
  @Test
  @DisplayName("금액이 0 이하 - IllegalArgumentException")
  void sc004_applyDiscount_nonPositive_throws() {
    // given
    BigDecimal nonPositive = BigDecimal.ZERO;

    // when & then (예외 검증)
    assertThatThrownBy(() -> service.applyDiscount(nonPositive, 1L))
        .isInstanceOf(IllegalArgumentException.class);
  }

  /** scenarioRef: SC-005 / criteriaRef: AC-ORDER-404 */
  @Test
  @DisplayName("주문 상세 조회 - 미존재 시 OrderNotFoundException")
  void sc005_getOrderDetail_missing_throws() {
    // given
    when(orderRepository.findById(7L)).thenReturn(null);

    // when & then (예외 검증)
    assertThatThrownBy(() -> service.getOrderDetail(7L))
        .isInstanceOf(OrderNotFoundException.class);
  }

  /** scenarioRef: SC-006 / criteriaRef: AC-ORDER-001 */
  @Test
  @DisplayName("주문 상세 조회 - 할인 적용된 dto 반환")
  void sc006_getOrderDetail_found_returnsDiscountedDto() {
    // given
    when(orderRepository.findById(1L))
        .thenReturn(new Order(1L, 2L, new BigDecimal("100000"), "CONFIRMED"));

    // when
    OrderDetailDto dto = service.getOrderDetail(1L);

    // then
    assertThat(dto.getId()).isEqualTo(1L);
    assertThat(dto.getFinalAmount()).isEqualByComparingTo(new BigDecimal("88000"));
    assertThat(dto.getStatus()).isEqualTo("CONFIRMED");
  }
}
