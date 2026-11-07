plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("maven-publish")
}

group = "com.meshchat"
version = "0.2.0-experimental"

extensions.configure<com.android.build.api.dsl.LibraryExtension> {
    namespace = "com.meshchat.core.client"
    compileSdk = 36
    defaultConfig { minSdk = 24 }
    buildFeatures { aidl = true }
    // Only the public client and interface are distribution inputs. No host,
    // runtime, Python, storage, transport-policy or native adapter sources.
    sourceSets.getByName("main") {
        java.srcDir("../../plugins/tauri-plugin-mesh-runtime/android/src/main/java/com/meshchat/runtime/core")
        aidl.srcDir("../../plugins/tauri-plugin-mesh-runtime/android/src/main/aidl")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    publishing { singleVariant("release") { withSourcesJar() } }
}
kotlin { compilerOptions { jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17 } }

afterEvaluate {
    publishing {
        publications {
            create<MavenPublication>("release") {
                from(components["release"])
                artifactId = "core-client"
            }
        }
        repositories { maven { name = "staging"; url = uri(layout.buildDirectory.dir("repository")) } }
    }
}
