import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.meshchat.runtime.smoke"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.meshchat.runtime.smoke"
        minSdk = 24
        targetSdk = 36
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += "x86_64" }
    }
    // Exercise the same consumer rules as the production app, after R8.
    // The ephemeral CI APK uses a debug key and is never a release artifact.
    buildTypes {
        getByName("release") {
            optimization { enable = true }
            signingConfig = signingConfigs.getByName("debug")
            testProguardFiles("test-rules.pro")
        }
    }
    testBuildType = "release"
    sourceSets.getByName("androidTest").java.srcDir("../src/androidTest/java")
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { compilerOptions { jvmTarget = JvmTarget.JVM_17 } }

dependencies {
    implementation(project(":tauri-plugin-mesh-runtime"))
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
