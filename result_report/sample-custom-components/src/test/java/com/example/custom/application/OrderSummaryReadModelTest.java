package com.example.custom.application;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Pure unit test for a distance-2 custom stereotype ({@code @ReadModel} ->
 * {@code @UseCase} -> {@code @Component}). Transitive meta-annotation resolution
 * means the harness still treats this as a component test target.
 */
class OrderSummaryReadModelTest {

  private final OrderSummaryReadModel readModel = new OrderSummaryReadModel();

  /** scenarioRef SC-008: an order with no line items is described as empty. */
  @Test
  @DisplayName("라인아이템이 없으면 비어있다고 설명한다")
  void sc008_noLineItems_describesEmpty() {
    // given
    long orderId = 42L;

    // when
    String description = readModel.describe(orderId, 0);

    // then
    assertThat(description).isEqualTo("order 42 is empty");
  }

  /** scenarioRef SC-009: an order with line items reports the count. */
  @Test
  @DisplayName("라인아이템이 있으면 개수를 보고한다")
  void sc009_withLineItems_reportsCount() {
    // given
    long orderId = 42L;

    // when
    String description = readModel.describe(orderId, 3);

    // then
    assertThat(description).isEqualTo("order 42 has 3 item(s)");
  }
}
