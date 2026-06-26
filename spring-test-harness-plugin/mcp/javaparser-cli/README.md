# astcli — JavaParser AST CLI (repo-ast MCP 백엔드)

`repo_ast_server.py`가 정확한 Java AST/심볼 분석을 위해 호출하는 보조 CLI다.
**jar가 없어도** repo-ast 서버는 순수 Python 정규식 fallback으로 동작하므로, 이 빌드는 선택이지만 정확도를 위해 권장한다.

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
