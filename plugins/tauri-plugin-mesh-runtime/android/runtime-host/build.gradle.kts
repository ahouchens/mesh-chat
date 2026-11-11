import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.tasks.OutputDirectory

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
    id("maven-publish")
}

group = "com.meshchat"
version = "0.3.0-experimental"
val runtimeAbis = providers.gradleProperty("meshRuntimeAbis").orElse("arm64-v8a").get()
    .split(',').map(String::trim).filter(String::isNotEmpty)
require(runtimeAbis.isNotEmpty() && runtimeAbis.all { it in setOf("arm64-v8a", "x86_64") })
abstract class PrepareRuntimeSources : Sync() {
    // A tracked output property carries this producer into AGP's generated sources.
    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty
}
val runtimeSources = tasks.register<PrepareRuntimeSources>("prepareRuntimeSources") {
    from(fileTree("../src/main/java") {
        include("com/meshchat/runtime/Native*.kt", "com/meshchat/runtime/Bootstrap*.kt",
            "com/meshchat/runtime/CoreDispatch.kt", "com/meshchat/runtime/CoreFailureObservationState.kt",
            "com/meshchat/runtime/MeshCoreApiService.kt",
            "com/meshchat/runtime/MeshCoreRuntime.kt")
    })
    outputDirectory.set(layout.buildDirectory.dir("generated/runtimeSources"))
    into(outputDirectory)
}

// The legacy DSL advertises a source-set type that AGP 9's objects do not implement.
extensions.configure<com.android.build.api.dsl.LibraryExtension> {
    namespace = "com.meshchat.core.runtime.host"
    compileSdk = 36
    defaultConfig {
        minSdk = 24
        ndk { abiFilters += runtimeAbis }
        consumerProguardFiles("consumer-rules.pro")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging.resources {
        excludes.remove("/META-INF/LICENSE")
        excludes.remove("META-INF/LICENSE")
    }
    publishing { singleVariant("release") { withSourcesJar() } }
}
extensions.configure<com.android.build.api.variant.LibraryAndroidComponentsExtension> {
    onVariants(selector().all()) { variant ->
        checkNotNull(variant.sources.java).addGeneratedSourceDirectory(
            runtimeSources, PrepareRuntimeSources::outputDirectory)
    }
}
kotlin { compilerOptions { jvmTarget = JvmTarget.JVM_17 } }
tasks.named("preBuild") { dependsOn(runtimeSources) }
tasks.matching { it.name.lowercase().endsWith("sourcesjar") }.configureEach { dependsOn(runtimeSources) }

chaquopy {
    defaultConfig {
        version = "3.13"
        pip { install("-r", "../../../../service/requirements-mobile.lock") }
        pyc { src = true; pip = true; stdlib = true }
    }
}
chaquopy.sourceSets.getByName("main") { srcDir("../../../../service/src") }

dependencies {
    api(project(":mesh-core-client"))
    // ComponentActivity is part of MeshCoreRuntime.confirmUnlock's public ABI.
    api("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("io.github.webrtc-sdk:android:150.7871.01")
}

afterEvaluate {
    publishing {
        publications {
            create<MavenPublication>("release") {
                from(components["release"])
                artifactId = "core-runtime-host"
                pom {
                    name.set("Mesh Core application runtime host")
                    description.set("Experimental app-owned Python/native Core host, separate from the thin client SDK")
                    licenses { license { name.set("MIT"); url.set("https://opensource.org/license/mit") } }
                }
            }
        }
        repositories { maven { name = "staging"; url = uri(layout.buildDirectory.dir("repository")) } }
    }
}
