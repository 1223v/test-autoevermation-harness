package com.example.custom.annotation;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

import org.springframework.core.annotation.AliasFor;
import org.springframework.stereotype.Component;

/**
 * Custom stereotype: a class annotated with {@code @UseCase} is a Spring-managed
 * component because this annotation is itself meta-annotated with {@link Component}.
 *
 * <p>This is the canonical "custom component" pattern from the Spring reference
 * (Classpath Scanning and Managed Components): the {@code @Component} meta-annotation
 * causes {@code @UseCase} to be treated the same way as {@code @Component}.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Component
public @interface UseCase {

  /** Logical bean name, aliased onto {@link Component#value()}. */
  @AliasFor(annotation = Component.class)
  String value() default "";
}
