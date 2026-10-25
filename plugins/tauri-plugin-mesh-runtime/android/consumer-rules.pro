-keep class com.chaquo.python.** { *; }
-keep class com.meshchat.runtime.** { *; }

# The pinned WebRTC AAR ships no consumer rules. libjingle looks up Java
# classes, constructors, enums and callbacks by name through JNI. Keeping our
# wrapper alone does not preserve those entry points in an optimized APK.
-keep class org.webrtc.** { *; }
# JNI Zero bootstraps before org.webrtc lookups. Keep its annotated native
# entry points, but let R8 remove unused Java APIs: this AAR omits JniZeroJni,
# which is referenced only by the unused setJniClassLoader Java entry point.
-keep class org.jni_zero.** {
    @org.jni_zero.CalledByNative <methods>;
    @org.jni_zero.CalledByNativeUnchecked <methods>;
}
