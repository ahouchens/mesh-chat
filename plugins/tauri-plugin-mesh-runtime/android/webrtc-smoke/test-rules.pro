# AndroidX Test's optional compile-time annotations are not runtime code.
# These rules affect only the instrumentation APK, not the optimized app.
-dontshrink
-dontoptimize
-dontobfuscate
-dontwarn com.google.errorprone.annotations.CanIgnoreReturnValue
-dontwarn com.google.errorprone.annotations.MustBeClosed

# The runner selects individual test methods by their command-line names.
-keep class com.meshchat.runtime.NativeWebRtcInteropTest** { *; }
-keep class com.meshchat.runtime.SignalMailboxAndroidTest** { *; }
-keep class com.meshchat.runtime.NativeCallbackQueueTest** { *; }
-keep class com.meshchat.runtime.NativeSessionReservationsTest** { *; }
