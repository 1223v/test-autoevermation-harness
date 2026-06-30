package com.example.custom.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Pure unit test for a custom-stereotype component ({@code @UseCase}). The
 * harness now classifies {@code @UseCase} as a component, so it is tested the
 * same way as any {@code @Service} — plain Mockito-free unit test of its logic.
 */
class CreateOrderUseCaseTest {

  private final CreateOrderUseCase useCase = new CreateOrderUseCase();

  /** scenarioRef SC-001: non-VIP order is charged the full amount. */
  @Test
  @DisplayName("비VIP 주문은 할인 없이 원금 그대로 청구된다")
  void sc001_nonVip_chargesFullAmount() {
    // given
    BigDecimal amount = new BigDecimal("100000");

    // when
    BigDecimal result = useCase.finalAmount(amount, false);

    // then
    assertThat(result).isEqualByComparingTo(amount);
  }

  /** scenarioRef SC-002: VIP order at/above threshold gets a 10% discount. */
  @Test
  @DisplayName("임계금액 이상 VIP 주문은 10% 할인된다")
  void sc002_vipAtThreshold_appliesTenPercentDiscount() {
    // given
    BigDecimal amount = new BigDecimal("100000");

    // when
    BigDecimal result = useCase.finalAmount(amount, true);

    // then
    assertThat(result).isEqualByComparingTo(new BigDecimal("90000.00"));
  }

  /** scenarioRef SC-003: VIP order below threshold is not discounted. */
  @Test
  @DisplayName("임계금액 미만 VIP 주문은 할인되지 않는다")
  void sc003_vipBelowThreshold_noDiscount() {
    // given
    BigDecimal amount = new BigDecimal("99999");

    // when
    BigDecimal result = useCase.finalAmount(amount, true);

    // then
    assertThat(result).isEqualByComparingTo(amount);
  }

  /** scenarioRef SC-004: a non-positive amount is rejected. */
  @Test
  @DisplayName("0 이하 금액은 IllegalArgumentException을 던진다")
  void sc004_nonPositiveAmount_throws() {
    // given
    BigDecimal amount = BigDecimal.ZERO;

    // when & then
    assertThatThrownBy(() -> useCase.finalAmount(amount, false))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("positive");
  }
}
