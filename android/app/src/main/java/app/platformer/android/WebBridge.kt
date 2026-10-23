package app.platformer.android

import android.webkit.JavascriptInterface

/**
 * window.PlatformerAndroid для web/app.js: токен устройства вместо подписи Telegram,
 * выход, отклик вибрацией и цвет фона под системными панелями. Страница грузится
 * только с адреса Platformer — чужие ссылки открываются в браузере, мост им недоступен.
 */
class WebBridge(
    private val store: TokenStore,
    private val onSignOut: () -> Unit,
    private val onHaptic: (String) -> Unit,
    private val onTheme: (Int) -> Unit,
    private val onPermissions: () -> String = { "{}" },
    private val onFix: (String) -> Unit = {},
) {
    @JavascriptInterface
    fun token(): String = store.token.orEmpty()

    @JavascriptInterface
    fun platform(): String = "android"

    @JavascriptInterface
    fun signOut() = onSignOut()

    /** Доступы телефона: {"steps":"granted|denied|unavailable","notifications":true|false}. */
    @JavascriptInterface
    fun permissions(): String = onPermissions()

    /** Включить доступ: steps — шаги из Health Connect, notifications — уведомления. */
    @JavascriptInterface
    fun fix(kind: String?) {
        if (kind == "steps" || kind == "notifications") onFix(kind)
    }

    /** select · impact · success · warning · error */
    @JavascriptInterface
    fun haptic(kind: String?) {
        if (kind in KINDS) onHaptic(kind!!)
    }

    /** Цвет фона страницы «#rrggbb» — им красятся полосы под статус-баром и жестами. */
    @JavascriptInterface
    fun theme(color: String?) {
        val value = color?.trim().orEmpty()
        if (!HEX.matches(value)) return
        onTheme(0xFF000000.toInt() or value.substring(1).toInt(16))
    }

    private companion object {
        val KINDS = setOf("select", "impact", "success", "warning", "error")
        val HEX = Regex("^#[0-9a-fA-F]{6}$")
    }
}
