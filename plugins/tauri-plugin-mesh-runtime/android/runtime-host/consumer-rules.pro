-keep class com.chaquo.python.** { *; }
-keep class com.meshchat.runtime.** { *; }
-keep class org.webrtc.** { *; }
-keep class org.jni_zero.** {
    @org.jni_zero.CalledByNative <methods>;
    @org.jni_zero.CalledByNativeUnchecked <methods>;
}
