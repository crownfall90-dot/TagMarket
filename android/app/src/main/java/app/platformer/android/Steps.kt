package app.platformer.android

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.time.LocalDate
import java.util.concurrent.TimeUnit

/**
 * Шаги с телефона: Health Connect (туда пишут счётчик телефона, Google Fit, Samsung Health
 * и браслеты) → сервер Platformer. Читаем суммы по дням за неделю — Health Connect сам
 * убирает дубли от разных приложений — и отправляем раз в 15 минут и при открытии.
 */
object Steps {
    private const val DAYS = 7
    private const val PERIODIC = "platformer-steps"
    private const val NOW = "platformer-steps-now"

    val readSteps = HealthPermission.getReadPermission(StepsRecord::class)
    val readSleep = HealthPermission.getReadPermission(SleepSessionRecord::class)
    val readHeart = HealthPermission.getReadPermission(HeartRateRecord::class)
    val readResting = HealthPermission.getReadPermission(RestingHeartRateRecord::class)
    private val HEALTH = setOf(readSteps, readSleep, readHeart, readResting)

    /** Сон и пульс за день: что телефон знает, то и отправляем. */
    class DayHealth(val sleepHours: Double?, val pulse: Long?, val hrAvg: Long?, val hrMax: Long?) {
        val empty get() = sleepHours == null && pulse == null && hrAvg == null && hrMax == null
    }
    const val BACKGROUND = HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND

    fun available(context: Context) =
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE

    /** Что просить: шаги и, если Health Connect это умеет, чтение в фоне. */
    fun permissions(context: Context): Set<String> {
        val client = HealthConnectClient.getOrCreate(context)
        val background = client.features.getFeatureStatus(
            HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND
        ) == HealthConnectFeatures.FEATURE_STATUS_AVAILABLE
        return if (background) HEALTH + BACKGROUND else HEALTH
    }

    suspend fun grantedSet(context: Context): Set<String> =
        if (!available(context)) emptySet()
        else runCatching { HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions() }.getOrDefault(emptySet())

    /** Сон или пульс разрешены — для строки «Сон и пульс» в настройках. */
    suspend fun healthGranted(context: Context): Boolean = grantedSet(context).let { readSleep in it || readHeart in it || readResting in it }

    /**
     * Сон и пульс по дням из Health Connect. Сон — за ночь, которая заканчивается в этот день
     * (с 18:00 накануне до 18:00); пульс — средний и максимальный за день и пульс покоя.
     */
    suspend fun health(context: Context, days: Int): Map<String, DayHealth> {
        val granted = grantedSet(context)
        if (granted.none { it == readSleep || it == readHeart || it == readResting }) return emptyMap()
        val client = HealthConnectClient.getOrCreate(context)
        val today = LocalDate.now()
        val out = mutableMapOf<String, DayHealth>()
        for (back in days - 1 downTo 0) {
            val day = today.minusDays(back.toLong())
            val sleep = if (readSleep in granted) runCatching {
                client.aggregate(AggregateRequest(
                    metrics = setOf(SleepSessionRecord.SLEEP_DURATION_TOTAL),
                    timeRangeFilter = TimeRangeFilter.between(day.minusDays(1).atTime(18, 0), day.atTime(18, 0)),
                ))[SleepSessionRecord.SLEEP_DURATION_TOTAL]
            }.getOrNull()?.toMinutes()?.takeIf { it > 0 }?.let { Math.round(it / 6.0) / 10.0 } else null
            val range = TimeRangeFilter.between(day.atStartOfDay(), day.plusDays(1).atStartOfDay())
            val heart = if (readHeart in granted) runCatching {
                client.aggregate(AggregateRequest(metrics = setOf(HeartRateRecord.BPM_AVG, HeartRateRecord.BPM_MAX), timeRangeFilter = range))
            }.getOrNull() else null
            val resting = if (readResting in granted) runCatching {
                client.aggregate(AggregateRequest(metrics = setOf(RestingHeartRateRecord.BPM_AVG), timeRangeFilter = range))[RestingHeartRateRecord.BPM_AVG]
            }.getOrNull() else null
            val item = DayHealth(sleep, resting, heart?.get(HeartRateRecord.BPM_AVG), heart?.get(HeartRateRecord.BPM_MAX))
            if (!item.empty) out[day.toString()] = item
        }
        return out
    }

    suspend fun granted(context: Context): Boolean =
        available(context) && readSteps in HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions()

    fun schedule(context: Context) {
        val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val work = WorkManager.getInstance(context)
        work.enqueueUniquePeriodicWork(
            PERIODIC, ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<StepsWorker>(15, TimeUnit.MINUTES).setConstraints(network).build()
        )
        work.enqueueUniqueWork(
            NOW, ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<StepsWorker>().setConstraints(network).build()
        )
    }

    /** Есть ли хоть один источник: Health Connect (шаги, сон, пульс) или счётчик телефона. */
    suspend fun anySource(context: Context): Boolean =
        granted(context) || healthGranted(context) || StepRecorder.ready(context)

    /**
     * Шаги по дням из обоих источников: за каждый день — большее значение. Health Connect
     * отстаёт, если трекер телефона туда не пишет; счётчик телефона начинается с подписки.
     */
    suspend fun merged(context: Context, days: Int): List<Pair<String, Long>> {
        val fromHealth = if (granted(context)) lastDays(context, days).toMap() else emptyMap()
        val fromPhone = StepRecorder.lastDays(context, days)
        val today = LocalDate.now().toString()
        return (fromHealth.keys + fromPhone.keys + if (fromHealth.isNotEmpty() || fromPhone.isNotEmpty()) setOf(today) else emptySet())
            .sorted()
            .map { day -> day to maxOf(fromHealth[day] ?: 0L, fromPhone[day] ?: 0L) }
            .filter { it.second > 0 || it.first == today }
    }

    /** Отправить шаги сейчас (сегодня и вчера — то, что меняется); false — нечего или не вышло. */
    suspend fun syncNow(context: Context): Boolean {
        val token = TokenStore(context).token ?: return false
        if (!anySource(context)) return false
        val days = merged(context, 2)
        val extra = health(context, 2)
        if (days.isEmpty() && extra.isEmpty()) return false
        return runCatching {
            kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { Api.sendSteps(token, days, extra) }
        }.isSuccess
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
        WorkManager.getInstance(context).cancelUniqueWork(NOW)
    }

    suspend fun lastDays(context: Context, days: Int = DAYS): List<Pair<String, Long>> {
        val client = HealthConnectClient.getOrCreate(context)
        val today = LocalDate.now()
        return (days - 1 downTo 0).map { back ->
            val day = today.minusDays(back.toLong())
            val result = client.aggregate(
                AggregateRequest(
                    metrics = setOf(StepsRecord.COUNT_TOTAL),
                    // местное время телефона: «день» тот же, что видит человек
                    timeRangeFilter = TimeRangeFilter.between(day.atStartOfDay(), day.plusDays(1).atStartOfDay()),
                )
            )
            day.toString() to (result[StepsRecord.COUNT_TOTAL] ?: 0L)
        }.filter { it.second > 0 || it.first == today.toString() }
    }
}

class StepsWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val token = TokenStore(applicationContext).token ?: return Result.success()
        if (!Steps.anySource(applicationContext)) return Result.success()
        return try {
            StepRecorder.subscribe(applicationContext)
            val days = Steps.merged(applicationContext, 7)
            val extra = Steps.health(applicationContext, 7)
            if (days.isEmpty() && extra.isEmpty()) return Result.success()
            Api.sendSteps(token, days, extra)
            Result.success()
        } catch (e: Api.HttpError) {
            if (e.status == 401) {          // устройство отвязали — больше не стучимся
                Steps.cancel(applicationContext)
                Result.success()
            } else Result.retry()
        } catch (e: Exception) {
            Result.retry()
        }
    }
}
