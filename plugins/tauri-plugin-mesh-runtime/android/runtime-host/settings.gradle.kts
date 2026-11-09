pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
    plugins {
        id("com.android.library") version "9.3.1"
        id("org.jetbrains.kotlin.android") version "2.2.10"
        id("com.chaquo.python") version "17.0.0"
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "mesh-core-runtime-host"
include(":mesh-core-client")
project(":mesh-core-client").projectDir = file("../../../../sdk/kotlin")
