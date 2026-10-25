# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# Native WebRTC is reached from Chaquopy and from reflection-only lifecycle
# code, so R8 cannot see these references. Keep the names and all members.
-keep class com.meshchat.runtime.NativeWebRtcHost { *; }
-keep class com.meshchat.runtime.NativeWebRtcBridge { *; }
-keep class com.meshchat.runtime.NativeWebRtcContext { *; }
-keep class com.meshchat.runtime.MeshAvailabilityService { *; }

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}

# Uncomment this to preserve the line number information for
# debugging stack traces.
#-keepattributes SourceFile,LineNumberTable

# If you keep the line number information, uncomment this to
# hide the original source file name.
#-renamesourcefileattribute SourceFile