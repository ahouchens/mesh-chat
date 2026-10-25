-keep class com.chaquo.python.** { *; }
-keep class com.meshchat.runtime.** { *; }

# The pinned WebRTC AAR ships no consumer rules. libjingle looks up Java
# classes, constructors, enums and callbacks by name through JNI. Keeping our
# wrapper alone does not preserve those entry points in an optimized APK.
-keep class org.webrtc.** { *; }
