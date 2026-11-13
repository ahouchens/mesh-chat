plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.meshchat.core.independent"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.meshchat.core.independent"
        minSdk = 24
        targetSdk = 36
        ndk { abiFilters += "x86_64" }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { compilerOptions { jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17 } }
dependencies {
    implementation("com.meshchat:core-runtime-host:0.3.0-experimental")
    implementation("com.meshchat:core-client:0.3.0-experimental")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
