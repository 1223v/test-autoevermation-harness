# 보정 예시: TEST_RUNTIME_FAILED → assertion 수정 최소 패치

## 개요

`test-run-result.json`의 실패 케이스를 `test-fixer`가 처리하는 과정을 설명한다.
실패 원인은 비즈니스 로직 오류가 아니라 **assertion의 타입 불일치**이므로 최소 diff로 해결한다.

---

## 실패 상황

- **테스트**: `OrderControllerTest#listActiveOrders_singleOrder_returnsCorrectJsonStructure`
- **rootCauseClass**: `TEST_RUNTIME_FAILED`
- **오류 메시지**:
  ```
  JSON path "$.orders[0].totalAmount.amount" expected:<15000> but was:<15000.00>
  ```

### 원인 분석

Spring의 기본 `MappingJackson2HttpMessageConverter`는 `BigDecimal` 값을 직렬화할 때
`WRITE_BIGDECIMAL_AS_PLAIN` 설정에 따라 `15000.00`처럼 소수점 두 자리를 유지한다.
`jsonPath(...).value(15000)` — 즉 `int` 리터럴 비교 — 는 타입·표현 불일치로 실패한다.

수정 방향:
- `sleep` 추가 불필요 (타이밍 문제 아님)
- mock 추가·변경 불필요 (MockitoBean 설정은 올바름)
- ObjectMapper 전역 설정 변경 불필요 (테스트 한 건을 위한 전역 변경은 부작용 위험)
- **assertion만** `isNumber()` + `value(15000.00)` 조합으로 수정한다.

---

## 최소 패치 (diff)

```diff
--- a/src/test/java/com/example/order/OrderControllerTest.java
+++ b/src/test/java/com/example/order/OrderControllerTest.java
@@ -52,7 +52,7 @@
         .andExpect(jsonPath("$.orders[0].id").value(1))
         .andExpect(jsonPath("$.orders[0].status").value("CONFIRMED"))
-        .andExpect(jsonPath("$.orders[0].totalAmount.amount").value(15000))
+        .andExpect(jsonPath("$.orders[0].totalAmount.amount").value(15000.00))
         .andExpect(jsonPath("$.orders[0].totalAmount.currency").value("KRW"));
```

변경 범위: **1줄**, 다른 테스트·프로덕션 코드 무변경.

---

## 보정 원칙 준수 확인

| 항목 | 준수 여부 | 설명 |
|---|---|---|
| sleep 추가 금지 | 준수 | 타이밍 문제가 아님 |
| broad catch 추가 금지 | 준수 | 예외 억제 없음 |
| over-mock 금지 | 준수 | MockitoBean 설정 변경 없음 |
| 최소 diff | 준수 | 1줄 변경 |
| 재생성(full rewrite) 금지 | 준수 | 기존 테스트 구조 유지 |

---

## 재실행 대상

```json
{
  "rerunTargets": [
    "com.example.order.OrderControllerTest#listActiveOrders_singleOrder_returnsCorrectJsonStructure"
  ]
}
```

패치 적용 후 `./gradlew test --tests 'com.example.order.OrderControllerTest'` 로 대상만 재실행한다.
전체 test task 재실행은 불필요하다.
