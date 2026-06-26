package com.example.orders.application;

import com.example.orders.domain.Order;

/** 협력 객체(mocking seam) — 컨트롤러/서비스 테스트에서 mock 대상. */
public interface OrderRepository {
  Order findById(Long id);
}
