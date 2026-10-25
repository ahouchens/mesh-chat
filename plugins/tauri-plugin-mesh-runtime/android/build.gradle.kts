import org.jetbrains.kotlin.gradle.dsl.JvmTarget

val meshRuntimeAbis = providers.gradleProperty("meshRuntimeAbis")
    .orElse("arm64-v8a")
    .get()
    .split(',')
    .map(String::trim)
    .filter(String::isNotEmpty)

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python") version "17.0.0"
}

android {
    namespace = "com.meshchat.runtime"
    compileSdk = 36

    defaultConfig {
        minSdk = 24
        consumerProguardFiles("consumer-rules.pro")
        ndk {
            abiFilters += meshRuntimeAbis
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_17
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            install("-r", "../../../service/requirements-mobile.lock")
        }
        pyc {
            src = true
            pip = true
            stdlib = true
        }
    }
}

chaquopy.sourceSets.getByName("main") {
    srcDir("../../../service/src")
}

dependencies {
    implementation(project(":tauri-android"))
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.core:core-ktx:1.15.0")
    // Native data-channel transport for the opt-in background availability
    // service. Pin exactly; adoption is gated on 16 KB page-size verification
    // and the release APK size budget.
    implementation("io.github.webrtc-sdk:android:150.7871.01")
}
