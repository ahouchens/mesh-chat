plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("maven-publish")
}

group = "com.meshchat"
version = "0.3.0-experimental"

extensions.configure<com.android.build.api.dsl.LibraryExtension> {
    namespace = "com.meshchat.core.client"
    compileSdk = 36
    defaultConfig { minSdk = 24 }
    buildFeatures { aidl = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    publishing { singleVariant("release") { withSourcesJar() } }
}
kotlin { compilerOptions { jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17 } }
dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}

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
