package com.example.custom.application;

import com.example.custom.annotation.ReadModel;

/**
 * Component declared with {@code @ReadModel}, a distance-2 custom stereotype
 * ({@code @ReadModel} -> {@code @UseCase} -> {@code @Component}). Exercises
 * transitive meta-annotation resolution.
 */
@ReadModel
public class OrderSummaryReadModel {

  public String describe(long orderId, int lineItems) {
    if (lineItems <= 0) {
      return "order " + orderId + " is empty";
    }
    return "order " + orderId + " has " + lineItems + " item(s)";
  }
}
