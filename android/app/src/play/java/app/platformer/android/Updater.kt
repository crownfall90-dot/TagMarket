package app.platformer.android

import android.app.Activity
import android.app.AlertDialog
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.play.core.appupdate.AppUpdateInfo
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.appupdate.AppUpdateOptions
import com.google.android.play.core.install.model.AppUpdateType
import com.google.android.play.core.install.model.UpdateAvailability
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Версия из Google Play обновляется через сам Play.
 * - При входе в приложение (запуск или возвращение после минуты в фоне) — сразу,
 *   на весь экран; отказались — приложение закрывается.
 * - Пока приложение открыто, новая версия ищется раз в минуту и всплывает окном
 *   с «Обновить» и «Обновить позже»; «Позже» действует до выхода из приложения.
 */
class Updater(private val activity: ComponentActivity, @Suppress("UNUSED_PARAMETER") host: FrameLayout) {
    private val manager = AppUpdateManagerFactory.create(activity)
    private var required = true                             // отказ от обновления закрывает приложение
    private var launched = true
    private var stoppedAt = 0L
    private var deferred = 0
    private var dialog: AlertDialog? = null
    private val launcher = activity.registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK && required) activity.finish()
    }

    init {
        activity.lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStop(owner: LifecycleOwner) { stoppedAt = System.currentTimeMillis() }
        })
        activity.lifecycleScope.launch {
            activity.repeatOnLifecycle(Lifecycle.State.RESUMED) {
                while (true) {
                    delay(POLL_EVERY)
                    poll()
                }
            }
        }
    }

    /** Окно обновления рисует сам Google Play — своего обязательного у нас нет. */
    val blocking get() = false

    /** Окно с «Позже» — системный диалог, «Назад» закрывает его сам. */
    fun back(): Boolean = false

    fun onResume() {
        val now = System.currentTimeMillis()
        val entry = launched || (stoppedAt > 0 && now - stoppedAt >= GRACE)
        stoppedAt = 0L
        launched = false
        if (entry) deferred = 0
        manager.appUpdateInfo.addOnSuccessListener { info ->
            val resume = info.updateAvailability() == UpdateAvailability.DEVELOPER_TRIGGERED_UPDATE_IN_PROGRESS
            val fresh = info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE &&
                info.isUpdateTypeAllowed(AppUpdateType.IMMEDIATE)
            if (resume || (entry && fresh)) {
                dialog?.dismiss()
                start(info, mustUpdate = true)
            }
        }
    }

    /** Приложение открыто: вышла новая версия — окно с «Обновить» и «Обновить позже». */
    private fun poll() {
        if (dialog?.isShowing == true) return
        manager.appUpdateInfo.addOnSuccessListener { info ->
            val fresh = info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE &&
                info.isUpdateTypeAllowed(AppUpdateType.IMMEDIATE) && info.availableVersionCode() != deferred
            if (!fresh || dialog?.isShowing == true || activity.isFinishing) return@addOnSuccessListener
            dialog = AlertDialog.Builder(activity)
                .setTitle(R.string.update_live_title)
                .setMessage(R.string.update_live_play)
                .setPositiveButton(R.string.update_play_now) { _, _ -> start(info, mustUpdate = false) }
                .setNegativeButton(R.string.update_play_later) { _, _ -> deferred = info.availableVersionCode() }
                .setOnCancelListener { deferred = info.availableVersionCode() }
                .show()
        }
    }

    private fun start(info: AppUpdateInfo, mustUpdate: Boolean) {
        required = mustUpdate
        runCatching {
            manager.startUpdateFlowForResult(info, launcher, AppUpdateOptions.newBuilder(AppUpdateType.IMMEDIATE).build())
        }
    }

    private companion object {
        const val POLL_EVERY = 60 * 1000L
        const val GRACE = 60 * 1000L
    }
}
