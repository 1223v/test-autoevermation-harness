package com.example.custom.validation;

import java.math.BigDecimal;

import jakarta.validation.ConstraintValidator;
import jakarta.validation.ConstraintValidatorContext;

/**
 * Custom validator: pure logic, no Spring stereotype. The harness should still
 * pick this up as a test target (POJO) and generate a direct unit test of
 * {@link #isValid(BigDecimal, ConstraintValidatorContext)}.
 */
public class PositiveAmountValidator
    implements ConstraintValidator<PositiveAmount, BigDecimal> {

  @Override
  public boolean isValid(BigDecimal value, ConstraintValidatorContext context) {
    // null is treated as valid; @NotNull is responsible for null-checks.
    if (value == null) {
      return true;
    }
    return value.compareTo(BigDecimal.ZERO) > 0;
  }
}
