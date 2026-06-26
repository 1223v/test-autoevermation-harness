package com.example.orders.web;

import com.example.orders.application.OrderNotFoundException;
import com.example.orders.application.OrderQueryService;
import com.example.orders.application.dto.OrderDetailDto;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {

  private final OrderQueryService orderQueryService;

  public OrderController(OrderQueryService orderQueryService) {
    this.orderQueryService = orderQueryService;
  }

  @GetMapping("/api/orders/{id}")
  public OrderDetailDto getOrder(@PathVariable Long id) {
    return orderQueryService.getOrderDetail(id);
  }

  @ExceptionHandler(OrderNotFoundException.class)
  public ResponseEntity<String> handleNotFound(OrderNotFoundException ex) {
    return ResponseEntity.status(HttpStatus.NOT_FOUND).body("ORDER_NOT_FOUND");
  }
}
