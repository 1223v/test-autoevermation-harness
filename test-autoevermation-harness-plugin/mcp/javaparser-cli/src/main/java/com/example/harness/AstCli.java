package com.example.harness;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JarTypeSolver;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * JavaParser-based AST CLI for the repo-ast MCP server.
 *
 * <p>Usage: {@code java -jar astcli-1.0.0-shaded.jar <path-to-.java-or-srcRoot>}.
 * Emits a single JSON object on stdout matching the contract consumed by
 * {@code repo_ast_server.py#_normalize_java_cli_output}:
 *
 * <pre>
 * { "package": str, "imports": [str],
 *   "classes": [ { "name": str, "package": str, "annotations": [str], "extendsImplements": str,
 *                  "methods": [ {name, signature, returnType, parameters:[str],
 *                                annotations:[str], public:bool, invokedMethods:[str]} ],
 *                  "fields":  [ {name, type, annotations:[str]} ] } ],
 *   "unresolvedSymbols": [str] }
 * </pre>
 *
 * <p>By contract method bodies and call ARGUMENTS are NEVER emitted; only the
 * simple names of methods invoked inside each method body are exposed as
 * {@code invokedMethods} structure metadata (used by the scenario target-call
 * conformance gate). Symbol resolution uses
 * JavaParser symbol-solver (pinned 3.28.2). Unresolved types are collected
 * best-effort into {@code unresolvedSymbols} rather than failing the run.
 */
public final class AstCli {

    private AstCli() {
    }

    public static void main(String[] args) {
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        if (args.length < 1) {
            System.err.println("usage: java -jar astcli.jar <path-to-.java-or-srcRoot>");
            System.exit(2);
            return;
        }
        Path target = Paths.get(args[0]).toAbsolutePath().normalize();
        try {
            JsonObject out = analyze(target, args);
            System.out.println(out.render());
        } catch (Exception e) {
            // Emit a structured error object so the Python side can degrade gracefully.
            JsonObject err = new JsonObject();
            err.put("package", JsonValue.str(""));
            err.put("imports", new JsonArray());
            err.put("classes", new JsonArray());
            JsonArray unresolved = new JsonArray();
            unresolved.add(JsonValue.str("FATAL: " + e.getClass().getSimpleName() + ": " + e.getMessage()));
            err.put("unresolvedSymbols", unresolved);
            System.out.println(err.render());
            System.exit(1);
        }
    }

    private static JsonObject analyze(Path target, String[] args) throws IOException {
        Path srcRoot = inferSourceRoot(target);
        List<Path> sourceRoots = new ArrayList<>();
        List<Path> jars = new ArrayList<>();
        ParserConfiguration.LanguageLevel level = ParserConfiguration.LanguageLevel.CURRENT;
        for (int i = 1; i < args.length; i += 2) {
            if (i + 1 >= args.length) throw new IllegalArgumentException("Missing option value");
            switch (args[i]) {
                case "--language-level": level = ParserConfiguration.LanguageLevel.valueOf("JAVA_" + args[i + 1]); break;
                case "--source-root": sourceRoots.add(Paths.get(args[i + 1])); break;
                case "--classpath": jars.add(Paths.get(args[i + 1])); break;
                default: throw new IllegalArgumentException("Unknown option: " + args[i]);
            }
        }
        ParserConfiguration config = new ParserConfiguration().setLanguageLevel(level)
                .setCharacterEncoding(StandardCharsets.UTF_8);
        CombinedTypeSolver typeSolver = new CombinedTypeSolver();
        typeSolver.add(new ReflectionTypeSolver());
        if (srcRoot != null && Files.isDirectory(srcRoot)) {
            sourceRoots.add(srcRoot);
        }
        for (Path source : new LinkedHashSet<>(sourceRoots)) {
            typeSolver.add(new JavaParserTypeSolver(source.toFile(), config));
        }
        for (Path jar : jars) typeSolver.add(new JarTypeSolver(jar));
        config.setSymbolResolver(new JavaSymbolSolver(typeSolver));
        JavaParser parser = new JavaParser(config);

        List<Path> files = collectJavaFiles(target);
        Set<String> unresolved = new LinkedHashSet<>();
        JsonArray classes = new JsonArray();
        JsonArray problems = new JsonArray();
        String packageName = "";
        JsonArray imports = new JsonArray();
        boolean firstFile = true;

        for (Path file : files) {
            CompilationUnit cu;
            try {
                ParseResult<CompilationUnit> parsed = parser.parse(file);
                if (!parsed.isSuccessful()) {
                    parsed.getProblems().forEach(p -> problems.add(JsonValue.str(file + ": " + p.getVerboseMessage())));
                    unresolved.add("PARSE_FAILED: " + file);
                    continue;
                }
                cu = parsed.getResult().orElse(null);
            } catch (Exception ex) {
                unresolved.add("PARSE_FAILED: " + file.getFileName());
                continue;
            }
            if (cu == null) {
                unresolved.add("PARSE_FAILED: " + file.getFileName());
                continue;
            }
            // package/imports are per-compilation-unit (JavaParser API): resolve them
            // for THIS file so classes from a multi-file / multi-package directory each
            // carry their own package. The top-level package/imports stay the first CU
            // for backward compatibility (single-file callers see identical output).
            String cuPackage = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
            if (firstFile) {
                packageName = cuPackage;
                cu.getImports().forEach(i -> imports.add(JsonValue.str(i.getNameAsString())));
                firstFile = false;
            }
            for (TypeDeclaration<?> type : cu.findAll(TypeDeclaration.class)) {
                classes.add(describeClass(type, cuPackage, unresolved));
            }
        }

        JsonObject obj = new JsonObject();
        obj.put("package", JsonValue.str(packageName));
        obj.put("imports", imports);
        obj.put("classes", classes);
        JsonArray unresolvedArr = new JsonArray();
        for (String s : unresolved) {
            unresolvedArr.add(JsonValue.str(s));
        }
        obj.put("unresolvedSymbols", unresolvedArr);
        obj.put("parseProblems", problems);
        obj.put("languageLevel", JsonValue.str(level.name()));
        return obj;
    }

    private static JsonObject describeClass(
            TypeDeclaration<?> cls, String cuPackage, Set<String> unresolved) {
        JsonObject obj = new JsonObject();
        obj.put("name", JsonValue.str(cls.getNameAsString()));
        obj.put("fqcn", JsonValue.str(cls.getFullyQualifiedName().orElse(cls.getNameAsString())));
        obj.put("declarationKind", JsonValue.str(cls instanceof RecordDeclaration ? "record" : cls instanceof EnumDeclaration ? "enum" : cls instanceof ClassOrInterfaceDeclaration && ((ClassOrInterfaceDeclaration) cls).isInterface() ? "interface" : "class"));
        obj.put("package", JsonValue.str(cuPackage == null ? "" : cuPackage));
        obj.put("annotations", annotationsOf(cls.getAnnotations()));

        List<String> ei = new ArrayList<>();
        if (cls instanceof ClassOrInterfaceDeclaration) {
            ClassOrInterfaceDeclaration declaration = (ClassOrInterfaceDeclaration) cls;
            declaration.getExtendedTypes().forEach(t -> { ei.add("extends " + t.asString()); resolveType(t, "EXTENDS", unresolved); });
            declaration.getImplementedTypes().forEach(t -> { ei.add("implements " + t.asString()); resolveType(t, "IMPLEMENTS", unresolved); });
        }
        if (cls instanceof RecordDeclaration) ((RecordDeclaration) cls).getImplementedTypes().forEach(t -> resolveType(t, "IMPLEMENTS", unresolved));
        if (cls instanceof EnumDeclaration) ((EnumDeclaration) cls).getImplementedTypes().forEach(t -> resolveType(t, "IMPLEMENTS", unresolved));
        cls.getAnnotations().forEach(a -> resolveAnnotation(a, unresolved));
        obj.put("extendsImplements", JsonValue.str(String.join(", ", ei)));

        JsonArray methods = new JsonArray();
        for (MethodDeclaration m : cls.getMethods()) {
            methods.add(describeMethod(m, unresolved));
        }
        obj.put("methods", methods);

        JsonArray fields = new JsonArray();
        for (FieldDeclaration f : cls.getFields()) {
            String typeStr = f.getElementType().asString();
            resolveType(f.getElementType(), "FIELD", unresolved);
            f.getAnnotations().forEach(a -> resolveAnnotation(a, unresolved));
            JsonArray fieldAnnos = annotationsOf(f.getAnnotations());
            for (VariableDeclarator v : f.getVariables()) {
                JsonObject fo = new JsonObject();
                fo.put("name", JsonValue.str(v.getNameAsString()));
                fo.put("type", JsonValue.str(typeStr));
                fo.put("annotations", fieldAnnos);
                fields.add(fo);
            }
        }
        if (cls instanceof RecordDeclaration) {
            for (Parameter parameter : ((RecordDeclaration) cls).getParameters()) {
                resolveType(parameter.getType(), "RECORD_COMPONENT", unresolved);
                JsonObject field = new JsonObject();
                field.put("name", JsonValue.str(parameter.getNameAsString()));
                field.put("type", JsonValue.str(parameter.getTypeAsString()));
                field.put("annotations", annotationsOf(parameter.getAnnotations()));
                fields.add(field);
            }
        }
        obj.put("fields", fields);
        return obj;
    }

    private static JsonObject describeMethod(MethodDeclaration m, Set<String> unresolved) {
        JsonObject obj = new JsonObject();
        obj.put("name", JsonValue.str(m.getNameAsString()));

        String returnType = m.getType().asString();
        // Best-effort resolution to surface unresolved symbols (never fails the run).
        try {
            m.getType().resolve();
        } catch (Exception | StackOverflowError ex) {
            unresolved.add("RETURN_TYPE: " + m.getNameAsString() + " -> " + returnType);
        }
        obj.put("returnType", JsonValue.str(returnType));

        JsonArray params = new JsonArray();
        List<String> paramSig = new ArrayList<>();
        for (Parameter p : m.getParameters()) {
            resolveType(p.getType(), "PARAMETER", unresolved);
            p.getAnnotations().forEach(a -> resolveAnnotation(a, unresolved));
            String ps = p.getType().asString() + " " + p.getNameAsString();
            params.add(JsonValue.str(ps));
            paramSig.add(p.getType().asString());
        }
        obj.put("parameters", params);
        obj.put("annotations", annotationsOf(m.getAnnotations()));
        boolean isPublic = m.isPublic() || (m.getParentNode().orElse(null) instanceof ClassOrInterfaceDeclaration
                && ((ClassOrInterfaceDeclaration) m.getParentNode().get()).isInterface() && !m.isPrivate());
        obj.put("public", JsonValue.bool(isPublic));
        m.getAnnotations().forEach(a -> resolveAnnotation(a, unresolved));

        String signature = (isPublic ? "public " : "")
                + returnType + " " + m.getNameAsString()
                + "(" + String.join(", ", paramSig) + ")";
        obj.put("signature", JsonValue.str(signature));

        // Invoked method simple names only — never argument text or bodies.
        Set<String> calls = new LinkedHashSet<>();
        // Receiver-aware records ({name, scope}) so the conformance gate can tell
        // orderService.cancel() from paymentClient.cancel(). Scope is emitted only
        // when it is a bare receiver (identifier / this / field access name);
        // complex scope expressions may embed argument text, so they degrade to "".
        Set<String> callKeys = new LinkedHashSet<>();
        JsonArray invokedCalls = new JsonArray();
        JsonArray resolvedCalls = new JsonArray();
        m.findAll(MethodCallExpr.class).forEach(c -> {
            calls.add(c.getNameAsString());
            String scope = c.getScope().map(s -> {
                if (s.isNameExpr()) {
                    return s.asNameExpr().getNameAsString();
                }
                if (s.isThisExpr()) {
                    return "this";
                }
                if (s.isFieldAccessExpr()) {
                    return s.asFieldAccessExpr().getNameAsString();
                }
                return "";
            }).orElse("");
            String declaringType = "";
            String resolvedSignature = "";
            try {
                var resolved = c.resolve();
                declaringType = resolved.declaringType().getQualifiedName();
                resolvedSignature = resolved.getQualifiedSignature();
            } catch (Exception | StackOverflowError ex) { /* ambiguity remains explicit */ }
            if (callKeys.add(scope + "#" + c.getNameAsString() + "#" + resolvedSignature)) {
                JsonObject call = new JsonObject();
                call.put("name", JsonValue.str(c.getNameAsString()));
                call.put("scope", JsonValue.str(scope));
                invokedCalls.add(call);
                JsonObject detail = new JsonObject();
                detail.put("name", JsonValue.str(c.getNameAsString()));
                detail.put("scope", JsonValue.str(scope));
                detail.put("declaringType", JsonValue.str(declaringType));
                detail.put("resolvedSignature", JsonValue.str(resolvedSignature));
                resolvedCalls.add(detail);
            }
        });
        JsonArray invoked = new JsonArray();
        for (String c : calls) {
            invoked.add(JsonValue.str(c));
        }
        obj.put("invokedMethods", invoked);
        obj.put("invokedCalls", invokedCalls);
        obj.put("resolvedInvokedCalls", resolvedCalls);
        // Contract: never emit method bodies or call arguments.
        return obj;
    }

    private static JsonArray annotationsOf(List<? extends AnnotationExpr> annos) {
        JsonArray arr = new JsonArray();
        for (AnnotationExpr a : annos) {
            arr.add(JsonValue.str("@" + a.getNameAsString()));
        }
        return arr;
    }

    private static void resolveType(com.github.javaparser.ast.type.Type type, String kind, Set<String> unresolved) {
        try { type.resolve(); } catch (Exception | StackOverflowError ex) { unresolved.add(kind + ": " + type.asString()); }
    }

    private static void resolveAnnotation(AnnotationExpr annotation, Set<String> unresolved) {
        try { annotation.resolve(); } catch (Exception | StackOverflowError ex) { unresolved.add("ANNOTATION: " + annotation.getNameAsString()); }
    }

    private static List<Path> collectJavaFiles(Path target) throws IOException {
        List<Path> result = new ArrayList<>();
        if (Files.isRegularFile(target)) {
            if (target.toString().endsWith(".java")) {
                result.add(target);
            }
            return result;
        }
        if (Files.isDirectory(target)) {
            try (Stream<Path> walk = Files.walk(target)) {
                result = walk.filter(Files::isRegularFile)
                        .filter(p -> p.toString().endsWith(".java"))
                        .collect(Collectors.toList());
            }
        }
        return result;
    }

    /** Walk up from a file/dir to a conventional {@code src/main/java} root for symbol solving. */
    private static Path inferSourceRoot(Path target) {
        Path dir = Files.isDirectory(target) ? target : target.getParent();
        Path probe = dir;
        while (probe != null) {
            Path candidate = probe.resolve("src").resolve("main").resolve("java");
            if (Files.isDirectory(candidate)) {
                return candidate;
            }
            // Detect when we are already inside .../src/main/java/...
            if (probe.endsWith(Paths.get("src", "main", "java"))) {
                return probe;
            }
            probe = probe.getParent();
        }
        return dir;
    }

    // ------------------------------------------------------------------
    // Minimal dependency-free JSON writer (avoids extra runtime deps).
    // ------------------------------------------------------------------

    private interface JsonNode {
        void render(StringBuilder sb);
    }

    private static final class JsonValue implements JsonNode {
        private final String raw;

        private JsonValue(String raw) {
            this.raw = raw;
        }

        static JsonValue str(String s) {
            return new JsonValue("\"" + escape(s == null ? "" : s) + "\"");
        }

        static JsonValue bool(boolean b) {
            return new JsonValue(b ? "true" : "false");
        }

        @Override
        public void render(StringBuilder sb) {
            sb.append(raw);
        }
    }

    private static final class JsonArray implements JsonNode {
        private final List<JsonNode> items = new ArrayList<>();

        void add(JsonNode n) {
            items.add(n);
        }

        @Override
        public void render(StringBuilder sb) {
            sb.append('[');
            for (int i = 0; i < items.size(); i++) {
                if (i > 0) {
                    sb.append(',');
                }
                items.get(i).render(sb);
            }
            sb.append(']');
        }
    }

    private static final class JsonObject implements JsonNode {
        private final List<String> keys = new ArrayList<>();
        private final List<JsonNode> values = new ArrayList<>();

        void put(String key, JsonNode value) {
            keys.add(key);
            values.add(value);
        }

        @Override
        public void render(StringBuilder sb) {
            sb.append('{');
            for (int i = 0; i < keys.size(); i++) {
                if (i > 0) {
                    sb.append(',');
                }
                sb.append('"').append(escape(keys.get(i))).append("\":");
                values.get(i).render(sb);
            }
            sb.append('}');
        }

        String render() {
            StringBuilder sb = new StringBuilder();
            render(sb);
            return sb.toString();
        }
    }

    private static String escape(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.toString();
    }
}
