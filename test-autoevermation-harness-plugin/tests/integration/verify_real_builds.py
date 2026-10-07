"""Opt-in real Spring/JUnit/JaCoCo builds. Downloads fixture dependencies once.

Run with SDK2 Python and JAVA_HOME pointing at JDK17:
  python tests/integration/verify_real_builds.py /absolute/empty/output-directory
No harness runtime dependencies are added. Results and fixtures stay in output.
"""
import importlib.util
import json
from pathlib import Path
import sys

PLUGIN = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('build_server_integration', PLUGIN/'mcp/build_test_server.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

SOURCE = '''package demo;
import org.springframework.stereotype.Service;
@Service public class CountService {
 public int count(int input) { if (input < 0) throw new IllegalArgumentException(); return input + 1; }
}
'''
TEST = '''package demo;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class CountTest {
 @Test void 한글메서드() { assertEquals(2,new CountService().count(1)); }
 @Test void negative() { assertThrows(IllegalArgumentException.class, () -> new CountService().count(-1)); }
}
'''
OTHER = '''package demo;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class OtherTest { @Test void zero() { assertEquals(1,new CountService().count(0)); } }
'''
INTEGRATION = '''package demo;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.context.junit.jupiter.SpringJUnitConfig;
import static org.junit.jupiter.api.Assertions.*;
@SpringJUnitConfig(CountService.class)
class CountIT { @Autowired CountService service; @Test void 한글통합() { assertEquals(2,service.count(1)); } }
'''
SKIPPED = '''package demo;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Disabled;
@Disabled class SkippedTest { @Test void skipped() {} }
'''
GRADLE = '''plugins { id 'java'; id 'jacoco' }
// Spring Boot version '3.2.0' fixture; dependency platform only, no packaging plugin.
repositories { mavenCentral() }
dependencies {
 implementation platform('org.springframework.boot:spring-boot-dependencies:3.2.0')
 implementation 'org.springframework:spring-context'
 testImplementation 'org.springframework.boot:spring-boot-starter-test'
 testRuntimeOnly 'org.junit.platform:junit-platform-launcher'
}
java { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
jacoco { toolVersion = '0.8.12' }
test { useJUnitPlatform(); exclude '**/*IT.class' }
jacocoTestReport { reports { xml.required = true }; dependsOn test }
tasks.register('integrationTest', Test) {
 testClassesDirs = sourceSets.test.output.classesDirs
 classpath = sourceSets.test.runtimeClasspath
 useJUnitPlatform(); include '**/*IT.class'
}
tasks.register('jacocoIntegrationReport', JacocoReport) {
 dependsOn integrationTest
 executionData integrationTest
 sourceSets sourceSets.main
 reports { xml.required = true }
}
'''
POM = '''<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
<parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.2.0</version><relativePath/></parent>
<groupId>demo</groupId><artifactId>contract-fixture</artifactId><version>1.0</version>
<properties><java.version>17</java.version><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>
<dependencies>
<dependency><groupId>org.springframework</groupId><artifactId>spring-context</artifactId></dependency>
<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>
</dependencies><build><plugins>
<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin>
<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-failsafe-plugin</artifactId><version>3.2.5</version><executions><execution><goals><goal>integration-test</goal><goal>verify</goal></goals></execution></executions></plugin>
<plugin><groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId><version>0.8.12</version><executions><execution><goals><goal>prepare-agent</goal></goals></execution></executions></plugin>
</plugins></build></project>
'''

def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    def record(name, value):
        results[name] = value
        (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        print(name, value.get('status'), value.get('passed'), flush=True)
        return value
    for tool in ('gradle','maven'):
        root = output/tool
        main = root/'src/main/java/demo/CountService.java'
        main.parent.mkdir(parents=True); main.write_text(SOURCE)
        testdir = root/'src/test/java/demo'; testdir.mkdir(parents=True)
        for name,text in [('CountTest',TEST),('OtherTest',OTHER),('CountIT',INTEGRATION),('SkippedTest',SKIPPED)]:
            (testdir/(name+'.java')).write_text(text)
        (root/('build.gradle' if tool=='gradle' else 'pom.xml')).write_text(GRADLE if tool=='gradle' else POM)
        if tool=='gradle': (root/'settings.gradle').write_text("rootProject.name='contract-fixture'\n")
        def run(label, patterns, **kw):
            return record(tool+'/'+label, build.run_targeted_tests(tool, root=str(root), test_patterns=patterns, **kw))
        # Explicit online priming applies only to these isolated fixtures.
        first=run('prime-and-multiple',['demo.CountTest','demo.OtherTest'],online=True)
        assert first['status']=='ok' and first['passed']==3, first
        tasks=record(tool+'/tasks',build.list_test_tasks(str(root)))
        assert tasks['status']=='ok',tasks
        korean=run('korean-method',['demo.CountTest#한글메서드'],with_coverage=False)
        assert korean['status']=='ok' and korean['passed']==1,korean
        integration=run('integration',['demo.CountIT#한글통합'],task='integrationTest' if tool=='gradle' else 'verify',
                        coverage_task='jacocoIntegrationReport' if tool=='gradle' else None, online=True)
        assert integration['status']=='ok' and integration['passed']==1,integration
        assert all(('integrationTest' if tool=='gradle' else 'failsafe-reports') in p for p in integration['reportPaths'])
        skipped=run('all-skipped',['demo.SkippedTest'],with_coverage=False)
        assert skipped['status']!='ok' and skipped['passed']==0,skipped
        missing=run('no-matching-tests',['demo.NonexistentTest'],with_coverage=False)
        assert missing['status']!='ok' and not missing['reportPaths'],missing
        main.write_text(SOURCE+'\nnot valid Java;\n')
        failed=run('compile-failure',['demo.CountTest'],with_coverage=False)
        assert failed['status']!='ok' and failed['exitCode']!=0 and not failed['reportPaths'],failed
        main.write_text(SOURCE)
        fixed=run('repaired',['demo.CountTest','demo.OtherTest'])
        assert fixed['status']=='ok' and fixed['passed']==3,fixed
        for label,excludes in [('included',[]),('excluded',['demo/CountService'])]:
            parsed=record(tool+'/coverage-'+label,build.parse_jacoco_report(str(root),packages=['demo'],excludes=excludes))
            gate=record(tool+'/gate-'+label,build.coverage_gate(str(root),packages=['demo'],excludes=excludes))
            state=record(tool+'/resume-'+label,build.detect_pipeline_state(str(root),packages=['demo'],excludes=excludes))
            assert parsed['coverageScope']=={'packages':['demo'],'excludes':excludes}
            assert gate['pass'] == (label=='included'),gate
    return results

if __name__=='__main__':
    verify(Path(sys.argv[1]).resolve())
