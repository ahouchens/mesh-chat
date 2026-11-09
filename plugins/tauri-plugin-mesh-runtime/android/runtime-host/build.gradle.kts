import org.jetbrains.kotlin.gradle.dsl.JvmTarget

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
val runtimeSources = tasks.register<Sync>("prepareRuntimeSources") {
    from(fileTree("../src/main/java") {
        include("com/meshchat/runtime/Native*.kt", "com/meshchat/runtime/Bootstrap*.kt",
            "com/meshchat/runtime/CoreDispatch.kt", "com/meshchat/runtime/MeshCoreApiService.kt",
            "com/meshchat/runtime/MeshCoreRuntime.kt")
    })
    into(layout.buildDirectory.dir("generated/runtimeSources"))
}

android {
    namespace = "com.meshchat.core.runtime.host"
    compileSdk = 36
    defaultConfig {
        minSdk = 24
        ndk { abiFilters += runtimeAbis }
        consumerProguardFiles("consumer-rules.pro")
    }
    sourceSets.getByName("main").java.srcDir(runtimeSources.map { it.destinationDir })
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
    implementation("androidx.activity:activity-ktx:1.10.1")
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
