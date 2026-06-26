package com.example.orders.domain;

import java.math.BigDecimal;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.validation.constraints.NotNull;

/** JPA 엔티티 — javax.persistence 사용(Boot 2.x 네임스페이스 감지 신호). */
@Entity
public class Order {

  @Id private Long id;

  @NotNull private Long customerId;

  @NotNull private BigDecimal amount;

  private String status;

  protected Order() {}

  public Order(Long id, Long customerId, BigDecimal amount, String status) {
    this.id = id;
    this.customerId = customerId;
    this.amount = amount;
    this.status = status;
  }

  public Long getId() {
    return id;
  }

  public Long getCustomerId() {
    return customerId;
  }

  public BigDecimal getAmount() {
    return amount;
  }

  public String getStatus() {
    return status;
  }
}
