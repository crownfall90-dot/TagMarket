package app.platformer.android

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Уведомления на телефон: те же события, что в колокольчике приложения (пополнения,
 * выводы, профит, напоминания). WorkManager раз в 15 минут спрашивает у сервера новые
 * события и показывает их системными уведомлениями. Пока приложение открыто, их
 * показывает сама страница — системные не дублируем.
 */
object Alerts {
    private const val CHANNEL = "events"
    private const val PERIODIC = "platformer-alerts"
    private const val PREFS = "alerts"
    private const val MAX_AT_ONCE = 5

    /** Приложение на экране: события видны в нём, системные уведомления не нужны. */
    @Volatile
    var foreground = false

    fun channel(context: Context) {
        NotificationManagerCompat.from(context).createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL, NotificationManagerCompat.IMPORTANCE_DEFAULT)
                .setName(context.getString(R.string.alerts_channel))
                .setDescription(context.getString(R.string.alerts_channel_text))
                .build()
        )
    }

    fun allowed(context: Context): Boolean =
        (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
            NotificationManagerCompat.from(context).areNotificationsEnabled()

    fun schedule(context: Context) {
        channel(context)
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC, ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<AlertsWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()
    }

    /** Новые события с сервера → уведомления. Первый запуск только запоминает, что уже было. */
    @Synchronized
    fun check(context: Context, token: String) {
        val items = Api.notifications(token)
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val newest = items.maxOfOrNull { it.id } ?: return
        val last = prefs.getLong("last_id", -1L)
        prefs.edit().putLong("last_id", maxOf(newest, last)).apply()
        if (last < 0 || foreground || !allowed(context)) return
        val fresh = items.filter { it.id > last && !it.read }.sortedBy { it.id }.takeLast(MAX_AT_ONCE)
        fresh.forEach { show(context, it) }
    }

    /**
     * Мгновенное событие от сервера (Firebase). Номер запоминаем, чтобы проверка раз
     * в 15 минут не показала его второй раз.
     */
    @Synchronized
    fun deliver(context: Context, item: Api.Event) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val last = prefs.getLong("last_id", -1L)
        if (item.id <= last) return
        prefs.edit().putLong("last_id", item.id).apply()
        if (foreground || !allowed(context)) return
        channel(context)
        show(context, item)
    }

    private fun show(context: Context, item: Api.Event) {
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val body = item.body.replace(Regex("<[^>]+>"), "").trim()
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(context, R.color.notification))
            .setContentTitle(item.title)
            .setContentText(body.lineSequence().firstOrNull().orEmpty())
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_EVENT)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(item.id.toInt(), notification)
        } catch (_: SecurityException) {
            // разрешение забрали между проверкой и показом — просто пропускаем
        }
    }
}

class AlertsWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        // вышла новая версия — «Мы обновились», даже если вход не выполнен
        runCatching { UpdateNotice.check(applicationContext) }
        val token = TokenStore(applicationContext).token ?: return Result.success()
        return try {
            Alerts.check(applicationContext, token)
            Result.success()
        } catch (e: Api.HttpError) {
            if (e.status == 401) {          // устройство отвязали — больше не спрашиваем
                Alerts.cancel(applicationContext)
                Result.success()
            } else Result.retry()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}
