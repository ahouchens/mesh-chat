# AndroidJUnitRunner shares this dependency with the target app. AGP omits it
# from the test APK even when R8 removes it from the app, crashing the runner
# before any test starts. Keep this test infrastructure in the CI host only.
# WebRTC uses the runtime plugin's production consumer rules without overrides.
-keep class androidx.tracing.** { *; }

# The runner is compiled separately and may use stdlib entry points which the
# application does not (for example kotlin.jvm.internal.Lambda). AGP likewise
# treats the target APK as the provider of the shared Kotlin runtime.
-keep class kotlin.** { *; }

# Directly exercised by the saturation instrumentation in this test host.
-keep class com.meshchat.runtime.NativeCallbackQueue { *; }
-keep class com.meshchat.runtime.NativeSessionReservations** { *; }
