package com.example.custom.web;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import com.example.custom.application.CreateOrderUseCase;

/**
 * Slice test for a controller using the custom composed mapping {@code @GetJson}.
 *
 * <p>The HTTP path and method are NOT guessed: they are confirmed from the
 * {@code @GetJson("/orders/{id}/quote")} alias (overriding {@code @RequestMapping#path})
 * and the meta {@code @RequestMapping(method = GET)} — exactly the verification
 * the harness now flags via the composed-mapping riskPoint.
 *
 * <p>Boot 3.2 profile: jakarta / JUnit 5 / {@code @MockBean}.
 */
@WebMvcTest(OrderApiController.class)
class OrderApiControllerTest {

  @Autowired private MockMvc mockMvc;

  @MockBean private CreateOrderUseCase createOrderUseCase;

  /** scenarioRef SC-010: GET /orders/{id}/quote returns the final amount as JSON. */
  @Test
  @DisplayName("GET /orders/{id}/quote 는 최종금액 JSON을 반환한다")
  void sc010_getQuote_returnsFinalAmountJson() throws Exception {
    // given
    given(createOrderUseCase.finalAmount(any(BigDecimal.class), eq(true)))
        .willReturn(new BigDecimal("90000.00"));

    // when
    var result = mockMvc.perform(get("/orders/{id}/quote", 7L));

    // then
    result
        .andExpect(status().isOk())
        .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
        .andExpect(jsonPath("$.orderId").value(7))
        .andExpect(jsonPath("$.finalAmount").exists());
    verify(createOrderUseCase).finalAmount(any(BigDecimal.class), eq(true));
  }
}
