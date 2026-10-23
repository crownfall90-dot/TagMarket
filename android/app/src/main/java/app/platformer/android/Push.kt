package app.platformer.android

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlin.concurrent.thread

/**
 * Мгновенные уведомления через Firebase Cloud Messaging. Настройки Firebase приходят в
 * сборку из google-services.json (см. build.gradle.kts); без них ничего не делаем —
 * события по-прежнему приходят проверкой раз в 15 минут (Alerts).
 */
object Push {
    val configured: Boolean
        get() = BuildConfig.FCM_APP_ID.isNotBlank() && BuildConfig.FCM_API_KEY.isNotBlank() &&
            BuildConfig.FCM_PROJECT_ID.isNotBlank() && BuildConfig.FCM_SENDER_ID.isNotBlank()

    fun init(context: Context) {
        if (!configured || FirebaseApp.getApps(context).isNotEmpty()) return
        runCatching {
            FirebaseApp.initializeApp(
                context,
                FirebaseOptions.Builder()
                    .setApplicationId(BuildConfig.FCM_APP_ID)
                    .setApiKey(BuildConfig.FCM_API_KEY)
                    .setProjectId(BuildConfig.FCM_PROJECT_ID)
                    .setGcmSenderId(BuildConfig.FCM_SENDER_ID)
                    .build(),
            )
        }
    }

    /** После входа: получить FCM-токен телефона и отдать его серверу. */
    fun register(context: Context) {
        if (!configured) return
        init(context)
        runCatching {
            FirebaseMessaging.getInstance().token.addOnSuccessListener { token -> send(context, token) }
        }
    }

    fun send(context: Context, pushToken: String) {
        val token = TokenStore(context).token ?: return
        thread(name = "push-register") { runCatching { Api.registerPush(token, pushToken) } }
    }

    /** Выход: телефон больше не получает уведомления этого аккаунта. */
    fun unregister() {
        if (!configured) return
        runCatching { FirebaseMessaging.getInstance().deleteToken() }
    }
}

/** Сообщение от сервера: событие из колокольчика → системное уведомление. */
class PushService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        Push.send(applicationContext, token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val id = data["id"]?.toLongOrNull() ?: return
        if (TokenStore(applicationContext).token == null) return
        Alerts.deliver(applicationContext, Api.Event(id, data["title"].orEmpty().ifBlank { "Platformer" }, data["body"].orEmpty(), false))
    }
}
