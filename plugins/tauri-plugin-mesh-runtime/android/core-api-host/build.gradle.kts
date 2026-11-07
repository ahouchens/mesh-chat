plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "com.meshchat.core.hostfixture"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.meshchat.core.hostfixture"
        minSdk = 24
        targetSdk = 36
        ndk { abiFilters += "x86_64" }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { compilerOptions { jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17 } }
dependencies { implementation(project(":tauri-plugin-mesh-runtime")) }
