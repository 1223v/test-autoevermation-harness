package com.example.custom.annotation;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

import org.springframework.core.annotation.AliasFor;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;

/**
 * Custom composed request-mapping annotation: meta-annotated with
 * {@link RequestMapping} and fixing {@code method = GET} + a JSON content type.
 *
 * <p>Mirrors how Spring's own {@code @GetMapping} is built. The actual URL path
 * is supplied by {@link #value()} which is an {@code @AliasFor} override of
 * {@link RequestMapping#path()} — so the path is NOT visible on the bare
 * annotation name and must be read from the alias to build a MockMvc request.
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@RequestMapping(method = RequestMethod.GET, produces = "application/json")
public @interface GetJson {

  /** URL path, aliased onto {@link RequestMapping#path()}. */
  @AliasFor(annotation = RequestMapping.class, attribute = "path")
  String[] value() default {};
}
