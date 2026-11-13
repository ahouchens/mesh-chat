pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        exclusiveContent {
            forRepository { maven { url = uri("repository") } }
            filter { includeGroup("com.meshchat") }
        }
        google(); mavenCentral()
    }
}
rootProject.name = "mesh-core-app-owned-consumer"
include(":app")
