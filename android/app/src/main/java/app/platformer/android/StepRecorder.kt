package app.platformer.android

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.fitness.FitnessLocal
import com.google.android.gms.fitness.LocalRecordingClient
import com.google.android.gms.fitness.data.LocalDataType
import com.google.android.gms.fitness.data.LocalField
import com.google.android.gms.fitness.request.LocalDataReadRequest
import com.google.android.gms.tasks.Task
import kotlinx.coroutines.suspendCancellableCoroutine
import java.time.LocalDate
import java.time.ZoneId
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Шаги со счётчика телефона через Recording API сервисов Google Play: они сами считают
 * шаги в фоне по датчику — тому же, что у встроенного трекера, — и хранят до 10 дней.
 * Нужно разрешение «Физическая активность». Счёт начинается с подписки, поэтому
 * первый день может быть неполным. Health Connect при этом остаётся вторым источником.
 */
object StepRecorder {
    const val PERMISSION = Manifest.permission.ACTIVITY_RECOGNITION

    fun available(context: Context): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
            GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(
                context, LocalRecordingClient.LOCAL_RECORDING_CLIENT_MIN_VERSION_CODE
            ) == ConnectionResult.SUCCESS

    fun permitted(context: Context): Boolean =
        ContextCompat.checkSelfPermission(context, PERMISSION) == PackageManager.PERMISSION_GRANTED

    fun ready(context: Context) = available(context) && permitted(context)

    /** Подписка повторяется безопасно: сервисы Google Play просто подтверждают её. */
    suspend fun subscribe(context: Context): Boolean {
        if (!ready(context)) return false
        return runCatching {
            FitnessLocal.getLocalRecordingClient(context).subscribe(LocalDataType.TYPE_STEP_COUNT_DELTA).await()
        }.isSuccess
    }

    /** Шаги по дням за последние [days] дней: дата (ISO) → шаги. Пусто — источник недоступен. */
    suspend fun lastDays(context: Context, days: Int): Map<String, Long> {
        if (!ready(context)) return emptyMap()
        val zone = ZoneId.systemDefault()
        val today = LocalDate.now(zone)
        val start = today.minusDays((days - 1).toLong()).atStartOfDay(zone).toEpochSecond()
        val end = today.plusDays(1).atStartOfDay(zone).toEpochSecond()
        val request = LocalDataReadRequest.Builder()
            .aggregate(LocalDataType.TYPE_STEP_COUNT_DELTA)
            .bucketByTime(1, TimeUnit.DAYS)
            .setTimeRange(start, end, TimeUnit.SECONDS)
            .build()
        return runCatching {
            val response = FitnessLocal.getLocalRecordingClient(context).readData(request).await()
            val out = mutableMapOf<String, Long>()
            for (bucket in response.buckets) {
                val day = java.time.Instant.ofEpochSecond(bucket.getStartTime(TimeUnit.SECONDS)).atZone(zone).toLocalDate()
                val steps = bucket.dataSets.flatMap { it.dataPoints }.sumOf { it.getValue(LocalField.FIELD_STEPS).asInt().toLong() }
                if (steps > 0) out[day.toString()] = (out[day.toString()] ?: 0L) + steps
            }
            out
        }.getOrDefault(emptyMap())
    }

    private suspend fun <T> Task<T>.await(): T = suspendCancellableCoroutine { cont ->
        addOnSuccessListener { cont.resume(it) }
        addOnFailureListener { cont.resumeWithException(it) }
        addOnCanceledListener { cont.cancel() }
    }
}
