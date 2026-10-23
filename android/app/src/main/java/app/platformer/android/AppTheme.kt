package app.platformer.android

import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import androidx.core.graphics.ColorUtils

/**
 * Тема приложения: тёмная (по умолчанию) или светлая — та же, что выбрана в настройках
 * Platformer. Веб-часть сообщает её через мост (цвет фона страницы), здесь она
 * запоминается, и нативные экраны — вход, заставка, окно обновления, страница
 * «нет соединения» — открываются в той же теме: цвета берутся из values (светлая)
 * или values-night (тёмная) по ночному режиму, который мы задаём экрану сами.
 */
object AppTheme {
    private const val PREFS = "theme"
    private const val KEY_LIGHT = "light"
    private const val KEY_SYSTEM = "system_mode"

    fun light(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_LIGHT, false)

    /** Запомнить тему по цвету фона страницы. */
    fun remember(context: Context, background: Int) {
        val light = ColorUtils.calculateLuminance(background) > 0.5
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_LIGHT, false) != light || !prefs.contains(KEY_LIGHT)) {
            prefs.edit().putBoolean(KEY_LIGHT, light).apply()
        }
        syncSystem(context)
    }

    /**
     * Android 12+ рисует заставку при запуске сам, ещё до кода приложения, — по ночному
     * режиму приложения. Задаём его по нашей теме (только когда он меняется).
     */
    fun syncSystem(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        val mode = if (light(context)) UiModeManager.MODE_NIGHT_NO else UiModeManager.MODE_NIGHT_YES
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getInt(KEY_SYSTEM, -1) == mode) return
        runCatching { context.getSystemService(UiModeManager::class.java)?.setApplicationNightMode(mode) }
            .onSuccess { prefs.edit().putInt(KEY_SYSTEM, mode).apply() }
    }

    /** Ночной режим экрана по теме приложения: @color берутся из values-night или values. */
    fun override(context: Context): Configuration = Configuration().apply {
        uiMode = if (light(context)) Configuration.UI_MODE_NIGHT_NO else Configuration.UI_MODE_NIGHT_YES
    }

    /** Фон до загрузки страницы — как у веб-части, чтобы не мигало. */
    fun background(context: Context): Int = if (light(context)) 0xFFF3F3F5.toInt() else 0xFF0B0B0D.toInt()
}
