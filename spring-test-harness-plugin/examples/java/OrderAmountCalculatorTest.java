package com.example.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.example.order.domain.Money;
import java.math.BigDecimal;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/**
 * OrderAmountCalculator 순수 단위 테스트 — Spring 컨텍스트 없음.
 *
 * <p>동치류·경계값 분석:
 *
 * <ul>
 *   <li>할인율 0%: 원금 그대로 반환
 *   <li>할인율 경계 하한 0.01%: 최소 할인 적용
 *   <li>할인율 50%: 정상 중간값
 *   <li>할인율 100%: 전액 할인 → 0원
 *   <li>할인율 100% 초과: IllegalArgumentException
 *   <li>금액 0원: 할인 후에도 0원
 * </ul>
 *
 * <p>scenarioRef: SC-004 criteriaRef: AC-ORDER-002
 */
@DisplayName("OrderAmountCalculator - 할인 금액 계산 경계값 테스트")
class OrderAmountCalculatorTest {

  private final OrderAmountCalculator calculator = new OrderAmountCalculator();

  @ParameterizedTest(name = "원금={0}원, 할인율={1}% → 예상결과={2}원")
  @CsvSource({
    "10000, 0,      10000",
    "10000, 0.01,   9999",
    "10000, 50,     5000",
    "10000, 100,    0",
    "0,     50,     0",
    "99999, 33,     66999",
  })
  @DisplayName("정상 할인율 범위 내 금액 계산이 기대값과 일치한다")
  void sc004_applyDiscount_validRate_returnsExpectedAmount(
      long originalAmount, double discountRatePercent, long expectedAmount) {
    // given
    Money original = Money.of(new BigDecimal(originalAmount), "KRW");

    // when
    Money result = calculator.applyDiscount(original, discountRatePercent);

    // then
    assertThat(result.getAmount()).isEqualByComparingTo(new BigDecimal(expectedAmount));
    assertThat(result.getCurrency()).isEqualTo("KRW");
  }

  @ParameterizedTest(name = "할인율={0}% 는 허용 범위를 초과한다")
  @CsvSource({
    "100.01",
    "101",
    "200",
    "-0.01",
    "-100",
  })
  @DisplayName("허용 범위를 벗어난 할인율은 IllegalArgumentException을 던진다")
  void sc004_applyDiscount_outOfRangeRate_throwsIllegalArgumentException(double invalidRate) {
    // given
    Money original = Money.of(new BigDecimal("10000"), "KRW");

    // when & then (예외 검증 — 행위와 단언 병합)
    assertThatThrownBy(() -> calculator.applyDiscount(original, invalidRate))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("할인율은 0 이상 100 이하여야 합니다");
  }
}
