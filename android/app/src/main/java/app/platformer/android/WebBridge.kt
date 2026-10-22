package app.platformer.android

import android.webkit.JavascriptInterface

/**
 * window.PlatformerAndroid для web/app.js: токен устройства вместо подписи Telegram
 * и выход, когда сервер устройство больше не знает. Страница грузится только с
 * адреса Platformer — чужие ссылки открываются в браузере, мост им недоступен.
 */
class WebBridge(private val store: TokenStore, private val onSignOut: () -> Unit) {
    @JavascriptInterface
    fun token(): String = store.token.orEmpty()

    @JavascriptInterface
    fun platform(): String = "android"

    @JavascriptInterface
    fun signOut() = onSignOut()
}
