package app.platformer.android

import android.app.Application

/**
 * Приложение: при старте процесса подключаем Firebase, если сборка с его настройками,
 * и сверяем ночной режим системы с темой приложения — для заставки при запуске.
 */
class PlatformerApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Push.init(this)
        AppTheme.syncSystem(this)
    }
}
