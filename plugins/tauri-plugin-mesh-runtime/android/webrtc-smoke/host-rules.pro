# AndroidJUnitRunner shares this dependency with the target app. AGP omits it
# from the test APK even when R8 removes it from the app, crashing the runner
# before any test starts. Keep this test infrastructure in the CI host only.
# WebRTC uses the runtime plugin's production consumer rules without overrides.
-keep class androidx.tracing.** { *; }
