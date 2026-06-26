package com.example.orders.application.dto;

/** 주문 상세 응답 DTO. */
public record OrderDetailDto(String id, String status, long amount) {
}
