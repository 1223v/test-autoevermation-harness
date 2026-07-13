# 빌드 능력 프로비저닝 + 의존성 캐시 프라이밍 (SSOT)

이 문서는 **대상 프로젝트의 빌드 파일**이 필수 커버리지 단계와 사용자가 활성화한 경우의 뮤테이션 단계를 돌릴 수 있도록 준비되어 있는지 점검하고(가능하면 함께 세팅), **콜드 의존성 캐시**로 인한 첫 실행 실패를 막는 **단일 출처(SSOT)**다. PITest는 기본 비활성 선택 기능이다.

> 정책 연계: 처리 규칙은 [fallback-policy.md](./fallback-policy.md) #17(빌드 능력)·#18(캐시 프라이밍).
> 환경 선세팅 흐름은 [environment-setup.md](./environment-setup.md) E11·E12. 시그니처는 `build-test` MCP의
> `detect_build_capabilities` / `check_dependency_cache` / `run_targeted_tests(online=True)`.

## 왜 필요한가 (사실 근거)

Phase E(E1–E10)는 **하네스 자신의 런타임**(Python·MCP SDK·JavaParser jar·JDK)만 세팅한다.
**대상 프로젝트의 빌드 파일**이 JaCoCo XML을 낼 수 있는지는 별개이며, 준비돼 있지 않으면 8단계(measure-coverage)가 깨진다. PITest를 명시적으로 활성화했다면 플러그인뿐 아니라 XML 출력까지 준비돼야 9단계(mutation-test)가 동작한다.

| 사실 | 결과 | 공식 출처 |
|---|---|---|
| Gradle JaCoCo 플러그인은 `jacocoTestReport`를 자동 생성하나 **XML 출력은 기본 OFF**(HTML만). XML은 `reports { xml.required = true }` 명시 필요 | `parse_jacoco_report`가 `jacoco.xml` 미발견 → `JACOCO_REPORT_NOT_FOUND` | [Gradle JaCoCo Plugin](https://docs.gradle.org/current/userguide/jacoco_plugin.html) |
| `pitest` 태스크는 `id 'info.solidsoft.pitest'` 플러그인을 적용해야 존재 | 미적용 시 9단계 "Task 'pitest' not found" | [gradle-pitest-plugin](https://gradle-pitest-plugin.solidsoft.info/) |
| JUnit5(Jupiter)는 `junit5PluginVersion`(=pitest-junit5-plugin) 필요 | 미설정 시 PITest가 Jupiter 테스트 미인식 | [pitest-junit5-plugin](https://github.com/pitest/pitest-junit5-plugin) |
| PIT의 기본 출력 형식은 **HTML**이며 XML은 명시적으로 추가해야 함 | 활성화했어도 `mutations.xml` 미생성 → `PITEST_REPORT_NOT_FOUND` | [PIT Maven quickstart](https://pitest.org/quickstart/maven/) · [gradle-pitest-plugin](https://gradle-pitest-plugin.solidsoft.info/) |
| Maven JaCoCo는 `prepare-agent` + `report`(verify 바인딩) 골을 명시해야 XML 생성 | 미바인딩 시 `jacoco.xml` 미생성 | [JaCoCo Maven Plug-in](https://www.eclemma.org/jacoco/trunk/doc/maven.html) |
| Gradle `--offline`은 **필요한 모듈이 캐시에 없으면 빌드를 일찍 실패**시킴 | 콜드 캐시/신규 플러그인 다운로드 필요 시 6단계 첫 실행 실패 | [Gradle Dependency Caching](https://docs.gradle.org/current/userguide/dependency_caching.html) |
| Maven `dependency:go-offline`은 의존성+플러그인을 일괄 다운로드(이후 오프라인 가능) | 콜드 캐시 1회 프라이밍 경로 | [dependency:go-offline](https://maven.apache.org/plugins/maven-dependency-plugin/go-offline-mojo.html) |

## 1. 빌드 능력 프로비저닝 (F1)

**감지(신호 전용).** `build-test.detect_build_capabilities(root, junit_engine, require_pitest=false)`는 빌드 파일을 읽어 `capabilities{jacoco, jacocoXml, pitest, pitestJunit5, pitestXml}` + `pitestRequired` + `missing[]` + 각 필수 누락에 대한 `proposedChanges[{file, anchor, snippet, reason, source}]`(최소 스니펫)을 반환한다. **파일을 수정하지 않는다.** `require_pitest=false`이면 PITest 능력은 정보로만 노출되고 `missing[]`이나 `status`에 영향을 주지 않는다.

**처리(detect → approve → inject).**

- 먼저 `HarnessConfig.mutation.enabled`를 확정한다. 미지정 기본값은 `false`; 대화형에서는 사용 여부를 묻고 CI에서는 명시적인 `true`만 opt-in으로 인정한다.
- **대화형**: JaCoCo와 PITest 누락을 분리해 보여준다. 승인한 `proposedChanges`만 빌드 파일에 최소 주입하고 `PipelineResult.buildChanges[]`에 기록한 뒤 같은 `require_pitest` 값으로 재감지한다. PITest 변경을 거부하면 `mutation.enabled:false`로 전환해 9단계만 `PITEST_DISABLED`로 건너뛴다. **침묵 주입 금지.**
- **비대화형·CI**: JaCoCo 누락, 또는 `mutation.enabled:true`인데 PITest 플러그인·어댑터·XML이 누락된 경우에만 자동 주입하지 않고 `status:"failed"` + remediation으로 중단한다. `mutation.enabled:false`인 경우 PITest 누락은 정상이다.

### 주입 스니펫 (공식 검증)

**Gradle (Groovy DSL)**
```groovy
plugins {
    id 'java'
    id 'jacoco'
    id 'info.solidsoft.pitest' version '1.19.0'
}
tasks.named('jacocoTestReport') { reports { xml.required = true } }   // XML 기본 OFF → 명시
pitest { junit5PluginVersion = '1.0.0' }                              // Jupiter 한정
pitest { outputFormats = ['XML', 'HTML']; timestampedReports = false } // PITest opt-in 시
```

**Gradle (Kotlin DSL)**
```kotlin
plugins {
    id("java")
    id("jacoco")
    id("info.solidsoft.pitest") version "1.19.0"
}
tasks.jacocoTestReport { reports { xml.required.set(true) } }
pitest { junit5PluginVersion.set("1.0.0") }
pitest { outputFormats.set(setOf("XML", "HTML")); timestampedReports.set(false) }
```

**Maven (`pom.xml` → `<build><plugins>`)**
```xml
<plugin>
  <groupId>org.jacoco</groupId>
  <artifactId>jacoco-maven-plugin</artifactId>
  <version>0.8.12</version>
  <executions>
    <execution><id>prepare-agent</id><goals><goal>prepare-agent</goal></goals></execution>
    <execution><id>report</id><phase>verify</phase><goals><goal>report</goal></goals></execution>
  </executions>
</plugin>
<plugin>
  <groupId>org.pitest</groupId>
  <artifactId>pitest-maven</artifactId>
  <version>1.19.0</version>
  <dependencies>   <!-- Jupiter 한정 -->
    <dependency>
      <groupId>org.pitest</groupId>
      <artifactId>pitest-junit5-plugin</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>
  <configuration>
    <outputFormats><value>XML</value><value>HTML</value></outputFormats>
    <timestampedReports>false</timestampedReports>
  </configuration>
</plugin>
```

> PITest 블록 전체는 `mutation.enabled:true`인 프로젝트에만 넣는다. JUnit4 프로파일(Boot 2.0–2.1)에서는 `junit5PluginVersion`/`pitest-junit5-plugin`을 넣지 않는다(`detect_build_capabilities(junit_engine="junit4", require_pitest=true)`는 `pitestJunit5`를 충족으로 처리).

## 2. 의존성 캐시 프라이밍 (F2)

**감지(신호 전용).** `build-test.check_dependency_cache(build_tool, root)`는 공유 캐시
(`~/.gradle/caches/modules-2`, `~/.m2/repository`) 유무로 `primed`를 추정한다. 프로젝트 단위 완전성은
보장 못 하므로 **콜드/신규 플러그인** 상황에선 1회 프라이밍을 권한다.

**처리.**
- **대화형**: `primed:false`이거나 방금 플러그인을 주입했다면 `AskUserQuestion("의존성/플러그인을 1회 온라인으로
  받아올까요?")` → "예"면 `run_targeted_tests(..., online=True)`를 **1회** 실행(또는 Maven `mvn dependency:go-offline`)
  → 이후 호출은 다시 오프라인. "아니오"면 오프라인 그대로 진행(실패 위험 고지).
- **비대화형·CI**: 자동 온라인 전환 금지. `BUILD_TEST_ALLOW_NETWORK=1` 옵트인 또는 사전 캐시 워밍업을
  remediation으로 안내. 미충족이면 첫 오프라인 실행 실패를 `partial`로 보고.

> 보안 자세는 유지된다(기본 네트워크 OFF, fallback-policy.md #14). 프라이밍은 **명시적 승인/옵트인**
> 1회 예외일 뿐, 상시 온라인이 아니다.

## 3. 단계 배치

- 두 항목은 **0.6단계**(configure-harness, 0.5 프로파일 확정 직후·인터뷰 전)에서 처리한다 —
  JaCoCo 에이전트는 `test` 실행 중 attach되므로 **6단계 run-tests 이전에** 빌드 능력이 갖춰져야 한다.
- `_workspace/00b_build_provision.json`에 감지·주입·프라이밍 결과를 보존(부분 재실행 시 재사용).
