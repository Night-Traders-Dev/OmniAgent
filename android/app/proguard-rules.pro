# OmniAgent proguard rules
-keep class com.omniagent.app.network.** { *; }
-keep class com.omniagent.app.service.** { *; }
-keepattributes Signature
-keepattributes *Annotation*
-dontwarn okhttp3.**
-dontwarn com.google.gson.**
