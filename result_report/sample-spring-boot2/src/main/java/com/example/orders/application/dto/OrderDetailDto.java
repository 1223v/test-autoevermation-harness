package com.example.orders.application.dto;

import java.math.BigDecimal;

public class OrderDetailDto {
  private final Long id;
  private final BigDecimal finalAmount;
  private final String status;

  public OrderDetailDto(Long id, BigDecimal finalAmount, String status) {
    this.id = id;
    this.finalAmount = finalAmount;
    this.status = status;
  }

  public Long getId() {
    return id;
  }

  public BigDecimal getFinalAmount() {
    return finalAmount;
  }

  public String getStatus() {
    return status;
  }
}
