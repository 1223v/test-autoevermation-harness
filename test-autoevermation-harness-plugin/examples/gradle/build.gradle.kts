// Spring Boot 4.1.0 + Java 17 + JUnit Platform (Jupiter 6.x, BOM-managed)
// JUnit 정책: jupiter-style (BOM 위임). strict-5x 고정이 필요하면 CHANGELOG의
// '정책 예외' 절차에 따라 junit.version 프로퍼티를 명시적으로 핀하고 회귀 위험을 기록할 것.

plugins {
    java
    jacoco
    id("org.springframework.boot") version "4.1.0"
    id("io.spring.dependency-management") version "1.1.7"
    // PITest 뮤테이션 테스트 (RESEARCH_NOTES §4)
    id("info.solidsoft.pitest") version "1.19.0"
}

group = "com.example"
version = "0.1.0-SNAPSHOT"

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")

    // spring-boot-starter-test: JUnit Jupiter, Mockito, AssertJ, Hamcrest — 모두 BOM 관리
    testImplementation("org.springframework.boot:spring-boot-starter-test")
}

// ── 테스트 태스크 설정 ────────────────────────────────────────────────────────
tasks.named<Test>("test") {
    // JUnit Platform (Jupiter 6.x) 사용
    useJUnitPlatform()

    // 보수적 병렬 설정: 파일시스템·포트 경합 방지. 슬라이스 테스트가 내장 서버를
    // 공유할 수 있으므로 2로 제한. 순수 단위 테스트만 있다면 CPU 코어 수까지 올릴 수 있다.
    maxParallelForks = 2

    // 콘솔 로그: 실패·스킵·통과 이벤트 + 예외 스택 출력
    testLogging {
        events("passed", "skipped", "failed")
        showExceptions = true
        showCauses = true
        showStackTraces = true
        exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL
    }

    // JUnit XML 리포트 위치: CI artifact 업로드 경로와 일치시킨다
    reports {
        junitXml.outputLocation = layout.buildDirectory.dir("test-results/test")
        html.outputLocation = layout.buildDirectory.dir("reports/tests/test")
    }

    // 시스템 프로퍼티: 타임존 고정으로 날짜 관련 flaky 방지
    systemProperty("user.timezone", "UTC")

    // 테스트 후 JaCoCo 리포트 자동 생성
    finalizedBy(tasks.named("jacocoTestReport"))
}

// ── JaCoCo 커버리지 (RESEARCH_NOTES §3, JaCoCo 0.8.12) ───────────────────────
jacoco {
    toolVersion = "0.8.12"
}

// near-100% 게이트 제외 allowlist (RESEARCH_NOTES §6): 생성코드/DTO/config/부트스트랩
val coverageExcludes = listOf(
    "**/*Application*",
    "**/config/**",
    "**/dto/**",
    "**/generated/**",
)

tasks.named<JacocoReport>("jacocoTestReport") {
    dependsOn(tasks.named("test"))
    reports {
        xml.required = true   // build-test-mcp parse_jacoco_report 가 소비
        html.required = true
    }
    classDirectories.setFrom(
        files(classDirectories.files.map {
            fileTree(it) { exclude(coverageExcludes) }
        })
    )
}

// 게이트: 미달 시 빌드 실패 (LINE/BRANCH/METHOD/CLASS)
tasks.named<JacocoCoverageVerification>("jacocoTestCoverageVerification") {
    dependsOn(tasks.named("jacocoTestReport"))
    classDirectories.setFrom(
        files(classDirectories.files.map {
            fileTree(it) { exclude(coverageExcludes) }
        })
    )
    violationRules {
        rule {
            limit { counter = "LINE";   value = "COVEREDRATIO"; minimum = "0.95".toBigDecimal() }
            limit { counter = "BRANCH"; value = "COVEREDRATIO"; minimum = "0.90".toBigDecimal() }
            limit { counter = "METHOD"; value = "COVEREDRATIO"; minimum = "0.95".toBigDecimal() }
            limit { counter = "CLASS";  value = "COVEREDRATIO"; minimum = "1.00".toBigDecimal() }
        }
    }
}

// check 시 커버리지 게이트 강제
tasks.named("check") {
    dependsOn(tasks.named("jacocoTestCoverageVerification"))
}

// ── PITest 뮤테이션 (RESEARCH_NOTES §4) ─────────────────────────────────────
pitest {
    // JUnit5 어댑터 자동 연결 (pitest-junit5-plugin 1.0.0+)
    junit5PluginVersion = "1.0.0"
    targetClasses = setOf("com.example.*")
    targetTests = setOf("com.example.*Test")
    excludedClasses = setOf(
        "com.example.*Application",
        "com.example.config.*",
        "com.example.*.dto.*",
    )
    mutators = setOf("DEFAULTS")
    mutationThreshold = 80          // mutation score < 80% 이면 빌드 실패
    threads = 2
    timestampedReports = false
    withHistory = true              // 증분 실행
    // 리포트: build/reports/pitest/ → build-test-mcp parse_pitest_report 가 소비
}
