package com.example.orders.application;

import com.example.orders.application.dto.OrderDetailDto;
import com.example.orders.domain.Order;
import java.math.BigDecimal;
import java.util.Optional;
import org.springframework.stereotype.Service;

/** 분기 로직(applyDiscount)을 가진 서비스 — 브랜치 커버리지/시나리오 대상. */
@Service
public class OrderQueryService {

  private final OrderRepository orderRepository;

  public OrderQueryService(OrderRepository orderRepository) {
    this.orderRepository = orderRepository;
  }

  public OrderDetailDto getOrderDetail(Long orderId) {
    Order order =
        Optional.ofNullable(orderRepository.findById(orderId))
            .orElseThrow(() -> new OrderNotFoundException("Order " + orderId + " not found"));
    BigDecimal finalAmount = applyDiscount(order.getAmount(), order.getCustomerId());
    return new OrderDetailDto(order.getId(), finalAmount, order.getStatus());
  }

  /** 금액·고객 등급에 따른 할인 분기(경계값 테스트 대상). */
  BigDecimal applyDiscount(BigDecimal amount, Long customerId) {
    if (amount == null || amount.signum() <= 0) {
      throw new IllegalArgumentException("amount must be positive");
    }
    BigDecimal rate;
    if (amount.compareTo(new BigDecimal("100000")) >= 0) {
      rate = new BigDecimal("0.10");
    } else if (amount.compareTo(new BigDecimal("50000")) >= 0) {
      rate = new BigDecimal("0.05");
    } else {
      rate = BigDecimal.ZERO;
    }
    // VIP 고객(짝수 id 가정) 추가 할인 분기
    if (customerId != null && customerId % 2 == 0) {
      rate = rate.add(new BigDecimal("0.02"));
    }
    return amount.subtract(amount.multiply(rate));
  }
}
