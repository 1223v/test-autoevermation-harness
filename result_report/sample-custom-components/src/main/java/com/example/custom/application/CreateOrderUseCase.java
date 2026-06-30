package com.example.custom.application;

import java.math.BigDecimal;

import com.example.custom.annotation.UseCase;

/**
 * Business component declared with the custom {@code @UseCase} stereotype
 * (meta-annotated with {@code @Component}). Has branching logic worth covering.
 */
@UseCase
public class CreateOrderUseCase {

  private static final BigDecimal VIP_THRESHOLD = new BigDecimal("100000");
  private static final BigDecimal VIP_DISCOUNT_RATE = new BigDecimal("0.10");

  /**
   * Applies a VIP discount when the order amount reaches the threshold.
   *
   * @throws IllegalArgumentException when {@code amount} is null or non-positive
   */
  public BigDecimal finalAmount(BigDecimal amount, boolean vip) {
    if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
      throw new IllegalArgumentException("amount must be positive");
    }
    if (vip && amount.compareTo(VIP_THRESHOLD) >= 0) {
      return amount.subtract(amount.multiply(VIP_DISCOUNT_RATE));
    }
    return amount;
  }
}
