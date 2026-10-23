package app.platformer.android

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Уведомление «Мы обновились»: фоновая проверка (раз в 15 минут, вместе с событиями)
 * читает latest.json из релиза. Вышла новая версия, а приложение закрыто — приходит
 * уведомление с кратким «что нового»; по нажатию открывается Platformer с окном
 * обновления. О каждой версии — один раз.
 */
object UpdateNotice {
    private const val CHANNEL = "updates"
    private const val PREFS = "updates"
    private const val ID = 7_000_001

    fun check(context: Context) {
        if (BuildConfig.UPDATE_URL.isBlank()) return
        val json = fetch() ?: return
        val code = json.optLong("versionCode")
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (code <= BuildConfig.VERSION_CODE || code <= prefs.getLong("notified", 0L)) return
        prefs.edit().putLong("notified", code).apply()
        // открыто — новая версия всплывёт в самом приложении
        if (Alerts.foreground || !Alerts.allowed(context)) return
        val notes = json.optJSONArray("notes")?.let { arr ->
            (0 until arr.length()).map { arr.optString(it).trim() }.filter { it.isNotEmpty() }.take(3)
        }.orEmpty()
        show(context, json.optString("versionName"), notes)
    }

    private fun fetch(): JSONObject? = runCatching {
        val conn = (URL(BuildConfig.UPDATE_URL + "?t=" + System.currentTimeMillis() / 60_000).openConnection() as HttpURLConnection).apply {
            connectTimeout = 10_000
            readTimeout = 15_000
            setRequestProperty("User-Agent", "PlatformerAndroid/${BuildConfig.VERSION_NAME}")
        }
        try {
            if (conn.responseCode != 200) return null
            val text = conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
            require(text.length <= 64 * 1024)
            JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }.getOrNull()

    private fun show(context: Context, version: String, notes: List<String>) {
        NotificationManagerCompat.from(context).createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL, NotificationManagerCompat.IMPORTANCE_DEFAULT)
                .setName(context.getString(R.string.update_channel))
                .setDescription(context.getString(R.string.update_channel_text))
                .build()
        )
        val open = PendingIntent.getActivity(
            context, ID,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val text = context.getString(R.string.update_push_text)
        val big = (listOf(text) + notes.map { "•  $it" }).joinToString("\n")
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(context, R.color.notification))
            .setContentTitle(context.getString(R.string.update_push_title, version))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(big))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(ID, notification)
        } catch (_: SecurityException) {
            // разрешение на уведомления забрали — просто пропускаем
        }
    }
}
