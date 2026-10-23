package app.platformer.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import androidx.core.content.IntentCompat

/** Ответ установщика Android: если система просит подтверждения — показываем её окно. */
class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            val confirm = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_INTENT, Intent::class.java)
            val shown = confirm != null && runCatching {
                context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }.isSuccess
            // окно подтверждения не открылось (так бывает в оболочках производителей) — это сбой:
            // в окне обновления появится «Скачать вручную»
            if (!shown) {
                listener?.invoke(PackageInstaller.STATUS_FAILURE, "установщик Android не открылся")
                return
            }
        }
        listener?.invoke(status, intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE))
    }

    companion object {
        @Volatile
        var listener: ((Int, String?) -> Unit)? = null
    }
}
