package com.example.orders.web;

import com.example.orders.application.OrderQueryService;
import com.example.orders.application.dto.OrderDetailDto;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderQueryService orderQueryService;

    public OrderController(OrderQueryService orderQueryService) {
        this.orderQueryService = orderQueryService;
    }

    @GetMapping("/{id}")
    public OrderDetailDto getOrder(@PathVariable String id) {
        return orderQueryService.getOrder(id);
    }
}
