-keep class com.chaquo.python.** { *; }
-keep class com.meshchat.runtime.** { *; }

# The pinned WebRTC AAR ships no consumer rules. libjingle looks up Java
# classes, constructors, enums and callbacks by name through JNI. Keeping our
# wrapper alone does not preserve those entry points in an optimized APK.
-keep class org.webrtc.** { *; }
# Recent WebRTC builds use Chromium's JNI Zero bootstrap before looking up
# org.webrtc classes. Its entry points are also called only from native code.
-keep class org.jni_zero.** { *; }
