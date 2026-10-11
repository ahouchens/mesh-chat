import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("rust")
}

val tauriProperties = Properties().apply {
    val propFile = file("tauri.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}

fun releaseValue(property: String, environment: String) =
    providers.gradleProperty(property).orElse(providers.environmentVariable(environment))

val releaseStoreFile = releaseValue("meshChatReleaseStoreFile", "MESH_CHAT_ANDROID_KEYSTORE_PATH")
val releaseStorePassword = releaseValue("meshChatReleaseStorePassword", "MESH_CHAT_ANDROID_KEYSTORE_PASSWORD")
val releaseKeyAlias = releaseValue("meshChatReleaseKeyAlias", "MESH_CHAT_ANDROID_KEY_ALIAS")
val releaseKeyPassword = releaseValue("meshChatReleaseKeyPassword", "MESH_CHAT_ANDROID_KEY_PASSWORD")
val missingReleaseSigning = listOf(
    "keystore path" to releaseStoreFile,
    "keystore password" to releaseStorePassword,
    "key alias" to releaseKeyAlias,
    "key password" to releaseKeyPassword,
).filterNot { it.second.isPresent }.map { it.first }

android {
    compileSdk = 36
    namespace = "com.meshchat.mobile"
    defaultConfig {
        manifestPlaceholders["usesCleartextTraffic"] = "false"
        applicationId = "com.meshchat.mobile"
        minSdk = 24
        targetSdk = 36
        versionCode = tauriProperties.getProperty("tauri.android.versionCode", "1").toInt()
        versionName = tauriProperties.getProperty("tauri.android.versionName", "1.0")
    }
    signingConfigs {
        if (missingReleaseSigning.isEmpty()) {
            create("meshChatRelease") {
                storeFile = file(releaseStoreFile.get())
                storePassword = releaseStorePassword.get()
                keyAlias = releaseKeyAlias.get()
                keyPassword = releaseKeyPassword.get()
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }
    buildTypes {
        getByName("debug") {
            isDebuggable = true
            isJniDebuggable = true
            isMinifyEnabled = false
        }
        getByName("release") {
            if (missingReleaseSigning.isEmpty()) {
                signingConfig = signingConfigs.getByName("meshChatRelease")
            }
            optimization {
               enable = true
            }
            proguardFiles(
                *fileTree(".") {
                  include("**/*.pro")
                  exclude("build/**")
                }.files.toTypedArray()
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    buildFeatures {
        buildConfig = true
    }
}

val validateReleaseSigning = tasks.register("validateReleaseSigning") {
    group = "verification"
    description = "Fail unless all external Mesh Chat release-signing inputs are usable."
    doLast {
        if (missingReleaseSigning.isNotEmpty()) {
            throw GradleException(
                "Mesh Chat release signing is not configured. Missing: ${missingReleaseSigning.joinToString()}. " +
                    "Supply meshChatRelease* Gradle properties or MESH_CHAT_ANDROID_* environment variables."
            )
        }
        if (!file(releaseStoreFile.get()).isFile) {
            throw GradleException("Mesh Chat release keystore path does not name a file.")
        }
    }
}

tasks.matching {
    it.name.contains("Release", ignoreCase = true) &&
        (it.name.startsWith("assemble", ignoreCase = true) || it.name.startsWith("bundle", ignoreCase = true))
}.configureEach {
    dependsOn(validateReleaseSigning)
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_1_8
    }
}

rust {
    rootDirRel = "../../../"
}

dependencies {
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-process:2.10.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test.ext:junit:1.1.4")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.0")
}

apply(from = file("tauri.build.gradle.kts"))
