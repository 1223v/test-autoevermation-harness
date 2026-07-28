# astcli — JavaParser AST CLI (repo-ast MCP 백엔드)

`repo_ast_server.py`가 정확한 Java AST/심볼 분석을 위해 호출하는 보조 CLI다.
**이 jar는 필수다.** repo-ast의 유일한 파싱 백엔드이며, jar 또는 JDK가 없으면 서버는 대체 경로 없이
`status:"failed"` + `JAVAPARSER_REQUIRED`로 **하드 실패**한다(fallback-policy.md #2). 환경 세팅
**Phase E·E6**이 자동 빌드하고 `${CLAUDE_PLUGIN_DATA}/javaparser/`로 persist하며, 실패 시 하드 중단한다.

> v0.16.0에서 JavaParser가 필수가 됐고(`.mcp.json`이 `REPO_AST_REQUIRE_JAVAPARSER=1` 설정),
> v0.31.0에서 도달 불가였던 정규식 fallback 추출기(~200줄)를 삭제했다. 그 결과
> `REPO_AST_REQUIRE_JAVAPARSER`는 **no-op**이다 — 설정하든 말든 jar 부재는 항상 하드 실패다.

## 요구사항
- **이 jar 빌드**: JDK 17+ (RESEARCH_NOTES §5의 Java 범위와 일치)
  - 참고: JDT LS(.lsp.json)는 **실행에 JDK 21+**를 요구한다 — 하네스 전체로 보면 빌드=17+, LSP 런타임=21+.
- Maven: **번들 wrapper(`./mvnw`)로 자동 조달되므로 시스템 Maven 설치는 선택**이다. 로컬에 Maven 3.6.3+이 있으면 `mvn`을 써도 된다.
- JavaParser symbol-solver **3.28.2** (pom.xml에 고정, RESEARCH_NOTES §2)

## 빌드
Maven wrapper가 번들되어 있으므로 시스템 Maven 없이 빌드할 수 있다.
```bash
cd mcp/javaparser-cli
./mvnw -q -DskipTests package        # Windows: mvnw.cmd -q -DskipTests package
```
산출물: `target/astcli-1.0.0-shaded.jar`

## 서버 연결
`repo_ast_server.py`의 jar 탐색 순서:
1. 환경변수 `REPO_AST_JAVAPARSER_JAR`(명시 경로)
2. `mcp/javaparser-cli/target/*-shaded.jar` → `*-jar-with-dependencies.jar` → `*.jar` (신선한 로컬 빌드 우선)
3. `${CLAUDE_PLUGIN_DATA}/javaparser/*.jar` — `scripts/persist_astcli_jar.py`가 복사해 둔
   **업데이트 생존 사본**(플러그인 캐시는 버전 키 스냅샷이라 업데이트마다 교체됨). 소스 지문
   (`astcli.fingerprint`)이 함께 기록되며, repo-ast `health()`가 `jarPersisted`/`jarStale`로 상태를 보고한다.

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
