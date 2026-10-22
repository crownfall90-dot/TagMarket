# Мост для страницы: методы вызываются из JavaScript по имени
-keepclassmembers class app.platformer.android.WebBridge {
    @android.webkit.JavascriptInterface <methods>;
}
