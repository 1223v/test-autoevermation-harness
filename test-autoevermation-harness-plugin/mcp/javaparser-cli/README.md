# astcli — JavaParser AST CLI (repo-ast MCP 백엔드)

`repo_ast_server.py`가 정확한 Java AST/심볼 분석을 위해 호출하는 보조 CLI다.
**이 jar는 권장이다(정밀 AST).** 기본 배포(`.mcp.json`)는 `REPO_AST_REQUIRE_JAVAPARSER`를 설정하지 않으므로,
jar/JDK가 없으면 서버는 **정규식 fallback으로 degrade**한다(`degraded:true` + 경고). 더 정확한 심볼 분석을 위해
환경 세팅 **Phase E·E6**에서 best-effort로 빌드한다 — 대화형=`AskUserQuestion` 후 함께 빌드 / CI=자동 빌드(실패 시 degrade).
정규식 fallback 없이 **하드실패를 강제**하려면 `REPO_AST_REQUIRE_JAVAPARSER=1`을 opt-in으로 설정한다 —
그때만 jar 부재 시 `JAVAPARSER_REQUIRED`로 실패한다.

## 요구사항
- JDK 17+ (RESEARCH_NOTES §5의 Java 범위와 일치)
- Maven 3.6.3+
- JavaParser symbol-solver **3.28.2** (pom.xml에 고정, RESEARCH_NOTES §2)

## 빌드
```bash
cd mcp/javaparser-cli
mvn -q -DskipTests package
```
산출물: `target/astcli-1.0.0-shaded.jar`

## 서버 연결
`repo_ast_server.py`의 jar 탐색 순서:
1. 환경변수 `REPO_AST_JAVAPARSER_JAR`(명시 경로)
2. `mcp/javaparser-cli/target/*-shaded.jar` → `*-jar-with-dependencies.jar` → `*.jar`

예:
```bash
export REPO_AST_JAVAPARSER_JAR="$(pwd)/target/astcli-1.0.0-shaded.jar"
```

## 직접 실행 (디버그)
```bash
java -jar target/astcli-1.0.0-shaded.jar path/to/Foo.java
```
출력 JSON 계약(서버 `_normalize_java_cli_output`이 소비):
```json
{
  "package": "com.example",
  "imports": ["..."],
  "classes": [{
    "name": "OrderController",
    "annotations": ["@RestController"],
    "extendsImplements": "",
    "methods": [{"name":"getOrder","signature":"public OrderDto getOrder(String id)",
                 "returnType":"OrderDto","parameters":["String id"],
                 "annotations":["@GetMapping"],"public":true}],
    "fields": [{"name":"service","type":"OrderQueryService","annotations":[]}]
  }],
  "unresolvedSymbols": []
}
```
**계약 보안**: 메서드 본문은 절대 출력하지 않는다(시그니처/애노테이션 메타만). 해석 실패 심볼은 `unresolvedSymbols`로 분리한다.
