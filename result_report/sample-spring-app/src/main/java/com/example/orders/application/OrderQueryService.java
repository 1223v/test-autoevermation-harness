package com.example.orders.application;

import com.example.orders.application.dto.OrderDetailDto;
import com.example.orders.domain.Order;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * 주문 조회 서비스. 분기 로직(등급별 할인)을 포함해 커버리지·뮤테이션 테스트 대상이 된다.
 */
@Service
public class OrderQueryService {

    private final Map<String, Order> store = Map.of(
        "ORD-100", new Order("ORD-100", "PAID", 12500L),
        "ORD-200", new Order("ORD-200", "PENDING", 30000L)
    );

    public OrderDetailDto getOrder(String id) {
        Order order = store.get(id);
        if (order == null) {
            throw new OrderNotFoundException(id);
        }
        long finalAmount = applyDiscount(order.baseAmount(), order.status());
        return new OrderDetailDto(order.id(), order.status(), finalAmount);
    }

    /** 상태와 금액 구간에 따른 할인 계산 — 다중 분기. */
    long applyDiscount(long amount, String status) {
        if (amount < 0) {
            throw new IllegalArgumentException("amount must be >= 0");
        }
        long discounted = amount;
        if ("PAID".equals(status)) {
            if (amount >= 20000L) {
                discounted = amount - (amount / 10); // 10% 할인
            } else {
                discounted = amount - (amount / 20); // 5% 할인
            }
        }
        return discounted;
    }
}
