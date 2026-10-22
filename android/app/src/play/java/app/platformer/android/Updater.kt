package app.platformer.android

import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.appupdate.AppUpdateOptions
import com.google.android.play.core.install.model.AppUpdateType
import com.google.android.play.core.install.model.UpdateAvailability

/** Версия из Google Play обновляется через сам Play: при запуске — сразу, на весь экран. */
class Updater(activity: ComponentActivity, @Suppress("UNUSED_PARAMETER") host: FrameLayout) {
    private val manager = AppUpdateManagerFactory.create(activity)
    private val launcher = activity.registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { }

    fun onResume() {
        manager.appUpdateInfo.addOnSuccessListener { info ->
            val resume = info.updateAvailability() == UpdateAvailability.DEVELOPER_TRIGGERED_UPDATE_IN_PROGRESS
            val fresh = info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE &&
                info.isUpdateTypeAllowed(AppUpdateType.IMMEDIATE)
            if (resume || fresh) {
                runCatching {
                    manager.startUpdateFlowForResult(info, launcher, AppUpdateOptions.newBuilder(AppUpdateType.IMMEDIATE).build())
                }
            }
        }
    }
}
