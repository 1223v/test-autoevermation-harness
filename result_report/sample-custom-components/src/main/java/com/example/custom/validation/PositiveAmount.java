package com.example.custom.validation;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

import jakarta.validation.Constraint;
import jakarta.validation.Payload;

/**
 * Custom bean-validation constraint backed by {@link PositiveAmountValidator}.
 * The class wired by {@code validatedBy} is a plain component-like unit that the
 * harness should generate a direct unit test for (isValid()).
 */
@Target({ElementType.FIELD, ElementType.PARAMETER})
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Constraint(validatedBy = PositiveAmountValidator.class)
public @interface PositiveAmount {

  String message() default "amount must be a positive value";

  Class<?>[] groups() default {};

  Class<? extends Payload>[] payload() default {};
}
