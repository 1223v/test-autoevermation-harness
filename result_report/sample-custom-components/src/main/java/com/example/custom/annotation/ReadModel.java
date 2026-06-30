package com.example.custom.annotation;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Distance-2 custom stereotype: meta-annotated with {@link UseCase}, which is
 * itself meta-annotated with {@code @Component}. Spring's component scanning
 * resolves the stereotype transitively, so a {@code @ReadModel} class is a bean.
 *
 * <p>Used to prove the harness resolves meta-annotations transitively, not just
 * one hop.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@UseCase
public @interface ReadModel {
}
