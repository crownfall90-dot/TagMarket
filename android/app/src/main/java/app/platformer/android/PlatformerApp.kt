package app.platformer.android

import android.app.Application

/** Приложение: при старте процесса подключаем Firebase, если сборка с его настройками. */
class PlatformerApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Push.init(this)
    }
}
