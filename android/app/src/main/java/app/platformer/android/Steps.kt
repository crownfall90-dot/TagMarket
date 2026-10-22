package app.platformer.android

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.permission.HealthPermission
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
    const val BACKGROUND = HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND

    fun available(context: Context) =
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE

    /** Что просить: шаги и, если Health Connect это умеет, чтение в фоне. */
    fun permissions(context: Context): Set<String> {
        val client = HealthConnectClient.getOrCreate(context)
        val background = client.features.getFeatureStatus(
            HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND
        ) == HealthConnectFeatures.FEATURE_STATUS_AVAILABLE
        return if (background) setOf(readSteps, BACKGROUND) else setOf(readSteps)
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

    /** Отправить шаги сейчас (сегодня и вчера — то, что меняется); false — нечего или не вышло. */
    suspend fun syncNow(context: Context): Boolean {
        val token = TokenStore(context).token ?: return false
        if (!granted(context)) return false
        val days = lastDays(context, 2)
        return runCatching {
            kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { Api.sendSteps(token, days) }
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
        if (!Steps.granted(applicationContext)) return Result.success()
        return try {
            Api.sendSteps(token, Steps.lastDays(applicationContext))
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
