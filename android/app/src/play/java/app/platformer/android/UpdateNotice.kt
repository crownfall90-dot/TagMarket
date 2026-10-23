package app.platformer.android

import android.content.Context

/** Версию из Google Play об обновлениях оповещает сам Play — своего уведомления нет. */
object UpdateNotice {
    @Suppress("UNUSED_PARAMETER")
    fun check(context: Context) = Unit

    @Suppress("UNUSED_PARAMETER")
    fun announce(context: Context, code: Long, version: String, notes: List<String>) = Unit
}
