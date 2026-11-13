plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.meshchat.core.consumer"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.meshchat.core.consumer"
        minSdk = 24
        targetSdk = 36
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { compilerOptions { jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17 } }
dependencies {
    implementation(files("../libs/mesh-core-client.aar"))
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
