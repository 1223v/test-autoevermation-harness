package com.example.custom.web;

import java.math.BigDecimal;
import java.util.Map;

import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import com.example.custom.annotation.GetJson;
import com.example.custom.application.CreateOrderUseCase;

/**
 * REST controller whose endpoint uses the custom composed mapping
 * {@link GetJson} instead of the built-in {@code @GetMapping}. The class is a
 * standard {@code @RestController} (so it is detected as a controller), but the
 * URL path lives on the composed annotation's aliased attribute.
 */
@RestController
public class OrderApiController {

  private final CreateOrderUseCase createOrderUseCase;

  public OrderApiController(CreateOrderUseCase createOrderUseCase) {
    this.createOrderUseCase = createOrderUseCase;
  }

  /** GET /orders/{id}/quote -> JSON quote. Path is on the @GetJson alias. */
  @GetJson("/orders/{id}/quote")
  public Map<String, Object> quote(@PathVariable("id") long id) {
    BigDecimal amount = createOrderUseCase.finalAmount(new BigDecimal("100000"), true);
    return Map.of("orderId", id, "finalAmount", amount);
  }
}
