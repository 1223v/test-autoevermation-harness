package com.example.custom.validation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import java.math.BigDecimal;

import jakarta.validation.ConstraintValidatorContext;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/**
 * Pure unit test for a custom {@link jakarta.validation.ConstraintValidator}.
 * No Spring context: the contract method {@code isValid} is exercised directly
 * and the {@link ConstraintValidatorContext} is a Mockito mock.
 */
class PositiveAmountValidatorTest {

  private final PositiveAmountValidator validator = new PositiveAmountValidator();
  private final ConstraintValidatorContext context = mock(ConstraintValidatorContext.class);

  /** scenarioRef SC-005: null is delegated to @NotNull and treated valid. */
  @Test
  @DisplayName("null 값은 유효한 것으로 간주한다")
  void sc005_nullValue_isValid() {
    // given
    BigDecimal value = null;

    // when
    boolean valid = validator.isValid(value, context);

    // then
    assertThat(valid).isTrue();
  }

  /** scenarioRef SC-006: strictly positive amounts pass. */
  @ParameterizedTest
  @ValueSource(strings = {"0.01", "1", "100000"})
  @DisplayName("양수 금액은 통과한다")
  void sc006_positiveAmount_isValid(String raw) {
    // given
    BigDecimal value = new BigDecimal(raw);

    // when
    boolean valid = validator.isValid(value, context);

    // then
    assertThat(valid).isTrue();
  }

  /** scenarioRef SC-007: zero and negative amounts are rejected. */
  @ParameterizedTest
  @ValueSource(strings = {"0", "-0.01", "-100"})
  @DisplayName("0 또는 음수 금액은 거부한다")
  void sc007_zeroOrNegativeAmount_isInvalid(String raw) {
    // given
    BigDecimal value = new BigDecimal(raw);

    // when
    boolean valid = validator.isValid(value, context);

    // then
    assertThat(valid).isFalse();
  }
}
