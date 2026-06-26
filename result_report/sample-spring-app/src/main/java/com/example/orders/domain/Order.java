package com.example.orders.domain;

/** 주문 도메인 엔티티(간소화). */
public class Order {
    private final String id;
    private final String status;
    private final long baseAmount;

    public Order(String id, String status, long baseAmount) {
        this.id = id;
        this.status = status;
        this.baseAmount = baseAmount;
    }

    public String id() {
        return id;
    }

    public String status() {
        return status;
    }

    public long baseAmount() {
        return baseAmount;
    }
}
