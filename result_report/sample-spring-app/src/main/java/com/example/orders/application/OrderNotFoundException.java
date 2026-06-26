package com.example.orders.application;

/** 주문을 찾지 못했을 때 발생. */
public class OrderNotFoundException extends RuntimeException {
    public OrderNotFoundException(String id) {
        super("order not found: " + id);
    }
}
