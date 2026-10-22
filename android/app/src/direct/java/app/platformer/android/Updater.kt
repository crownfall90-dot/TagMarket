package app.platformer.android

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Самообновление APK, установленного не из Google Play. При запуске (и не чаще раза
 * в 30 минут при возвращении) читает latest.json из релиза на GitHub; если версия
 * новее — качает APK, сверяет SHA-256, имя пакета, номер версии и подпись с
 * установленным приложением и ставит его через PackageInstaller. На Android 12+
 * обновление самого себя проходит без вопросов; на старых — одно «Установить».
 */
class Updater(private val activity: ComponentActivity, private val host: FrameLayout) {
    private class Release(val code: Long, val name: String, val apk: String, val sha256: String, val size: Long)

    private val prefs = activity.getSharedPreferences("updates", Context.MODE_PRIVATE)
    private var job: Job? = null
    private var overlay: View? = null
    private var waiting: Pair<Release, File>? = null       // скачано, ждём разрешения на установку
    private var launched = true                             // при открытии приложения проверяем всегда

    init {
        UpdateReceiver.listener = { status, message -> activity.runOnUiThread { onStatus(status, message) } }
    }

    fun onResume() {
        if (BuildConfig.UPDATE_URL.isBlank() || job?.isActive == true) return
        waiting?.let { (release, file) ->
            if (canInstall()) launchInstall(release, file)
            return
        }
        val now = System.currentTimeMillis()
        if (!launched && now - prefs.getLong("checked", 0L) < CHECK_EVERY) return
        launched = false
        job = activity.lifecycleScope.launch {
            try {
                val release = withContext(Dispatchers.IO) { fetch() }
                prefs.edit().putLong("checked", now).apply()
                if (release.code <= BuildConfig.VERSION_CODE) return@launch
                show(release)
                val file = withContext(Dispatchers.IO) { download(release) }
                withContext(Dispatchers.IO) { verify(release, file) }
                if (canInstall()) install(release, file) else askPermission(release, file)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // нет сети или релиза — молча; ошибку показываем, только если окно уже на экране
                if (overlay != null) fail(e.message ?: e.javaClass.simpleName)
            }
        }
    }

    // ── сеть ─────────────────────────────────────────────────────────────

    private fun open(url: String): HttpURLConnection {
        require(url.startsWith("https://")) { "только HTTPS" }
        return (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 10_000
            readTimeout = 20_000
            instanceFollowRedirects = true             // github.com → хранилище файлов, тоже HTTPS
            setRequestProperty("Accept", "application/octet-stream, application/json")
            setRequestProperty("User-Agent", "PlatformerAndroid/${BuildConfig.VERSION_NAME}")
        }
    }

    private fun fetch(): Release {
        val conn = open(BuildConfig.UPDATE_URL + "?t=" + System.currentTimeMillis() / 60_000)
        try {
            check(conn.responseCode == 200) { "HTTP ${conn.responseCode}" }
            val text = conn.inputStream.use { input ->
                val out = java.io.ByteArrayOutputStream()
                val buf = ByteArray(8 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    require(out.size() <= 64 * 1024) { "слишком длинный ответ" }
                }
                out.toString(Charsets.UTF_8.name())
            }
            val json = JSONObject(text)
            val apk = json.getString("apk")
            // APK — только из того же релиза, что и latest.json
            require(apk.startsWith(BuildConfig.UPDATE_URL.substringBeforeLast('/') + "/")) { "чужая ссылка" }
            val sha = json.getString("sha256").lowercase()
            require(Regex("^[0-9a-f]{64}$").matches(sha)) { "нет контрольной суммы" }
            return Release(json.getLong("versionCode"), json.optString("versionName"), apk, sha, json.optLong("size"))
        } finally {
            conn.disconnect()
        }
    }

    private suspend fun download(release: Release): File {
        val dir = File(activity.cacheDir, "updates").apply { mkdirs() }
        val file = File(dir, "platformer-${release.code}.apk")
        dir.listFiles()?.filter { it != file }?.forEach { it.delete() }
        if (file.exists() && sha256(file) == release.sha256) return file
        val conn = open(release.apk)
        try {
            check(conn.responseCode == 200) { "HTTP ${conn.responseCode}" }
            val total = conn.contentLengthLong.takeIf { it > 0 } ?: release.size
            require(total in 0..MAX_SIZE) { "слишком большой файл" }
            val tmp = File(dir, file.name + ".part")
            conn.inputStream.use { input ->
                tmp.outputStream().use { out ->
                    val buf = ByteArray(64 * 1024)
                    var done = 0L
                    var shown = -1
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        done += n
                        require(done <= MAX_SIZE) { "слишком большой файл" }
                        val pct = if (total > 0) (done * 100 / total).toInt() else -1
                        if (pct != shown) {
                            shown = pct
                            withContext(Dispatchers.Main) { progress(pct, total) }
                        }
                    }
                }
            }
            check(tmp.renameTo(file)) { "не удалось сохранить файл" }
            return file
        } finally {
            conn.disconnect()
        }
    }

    // ── проверка ─────────────────────────────────────────────────────────

    private fun sha256(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo?): Set<String> {
        val certs = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info?.signingInfo?.let { if (it.hasMultipleSigners()) it.apkContentsSigners else it.signingCertificateHistory }
        } else {
            info?.signatures
        }
        return certs.orEmpty().map { cert ->
            MessageDigest.getInstance("SHA-256").digest(cert.toByteArray()).joinToString("") { "%02x".format(it) }
        }.toSet()
    }

    @Suppress("DEPRECATION")
    private fun verify(release: Release, file: File) {
        if (sha256(file) != release.sha256) {
            file.delete()
            error("файл повреждён, скачаем заново")
        }
        val pm = activity.packageManager
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) PackageManager.GET_SIGNING_CERTIFICATES
        else PackageManager.GET_SIGNATURES
        val archive = pm.getPackageArchiveInfo(file.path, flags) ?: run { file.delete(); error("файл не читается") }
        require(archive.packageName == activity.packageName) { "это другое приложение" }
        val code = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) archive.longVersionCode else archive.versionCode.toLong()
        require(code == release.code && code > BuildConfig.VERSION_CODE) { "не та версия" }
        // подпись должна совпасть с установленной — иначе это не наша сборка
        val mine = signers(pm.getPackageInfo(activity.packageName, flags))
        val theirs = signers(archive)
        if (mine.isNotEmpty() && theirs.isNotEmpty() && mine.intersect(theirs).isEmpty()) {
            file.delete()
            error("подпись не совпадает")
        }
    }

    // ── установка ────────────────────────────────────────────────────────

    private fun canInstall() = activity.packageManager.canRequestPackageInstalls()

    private fun launchInstall(release: Release, file: File) {
        waiting = null
        job = activity.lifecycleScope.launch {
            try {
                show(release)
                install(release, file)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                fail(e.message ?: e.javaClass.simpleName)
            }
        }
    }

    private suspend fun install(release: Release, file: File) {
        state(release, activity.getString(R.string.update_installing), busy = true)
        withContext(Dispatchers.IO) {
            val installer = activity.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
                setAppPackageName(activity.packageName)
                setSize(file.length())
                setInstallReason(PackageManager.INSTALL_REASON_USER)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
                }
            }
            val id = installer.createSession(params)
            installer.openSession(id).use { session ->
                file.inputStream().use { input ->
                    session.openWrite("platformer.apk", 0, file.length()).use { out ->
                        input.copyTo(out)
                        session.fsync(out)
                    }
                }
                val intent = Intent(activity, UpdateReceiver::class.java).setPackage(activity.packageName)
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                    (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
                session.commit(PendingIntent.getBroadcast(activity, id, intent, flags).intentSender)
            }
        }
    }

    private fun onStatus(status: Int, message: String?) {
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION, PackageInstaller.STATUS_SUCCESS -> Unit
            PackageInstaller.STATUS_FAILURE_ABORTED -> hide()             // нажали «Отмена» в окне Android
            else -> fail(message ?: "ошибка $status")
        }
    }

    // ── окно ─────────────────────────────────────────────────────────────

    private fun show(release: Release) {
        if (overlay == null) {
            val view = LayoutInflater.from(activity).inflate(R.layout.view_update, host, false)
            host.addView(view)
            val card = view.findViewById<View>(R.id.update_card)
            view.alpha = 0f
            card.translationY = 80f * activity.resources.displayMetrics.density
            view.animate().alpha(1f).setDuration(220).start()
            card.animate().translationY(0f).setDuration(320).start()
            view.findViewById<Button>(R.id.update_later).setOnClickListener {
                job?.cancel()
                hide()
            }
            overlay = view
        }
        overlay!!.findViewById<TextView>(R.id.update_title).text =
            activity.getString(R.string.update_title, release.name.ifBlank { release.code.toString() })
        state(release, activity.getString(R.string.update_downloading, megabytes(release.size)), busy = true)
    }

    private fun state(release: Release?, text: String, busy: Boolean, action: String? = null, onAction: (() -> Unit)? = null) {
        val view = overlay ?: return
        release?.let {
            view.findViewById<TextView>(R.id.update_title).text =
                activity.getString(R.string.update_title, it.name.ifBlank { it.code.toString() })
        }
        view.findViewById<TextView>(R.id.update_text).text = text
        view.findViewById<ProgressBar>(R.id.update_progress).visibility = if (busy) View.VISIBLE else View.GONE
        val button = view.findViewById<Button>(R.id.update_action)
        button.visibility = if (action != null) View.VISIBLE else View.GONE
        button.text = action.orEmpty()
        button.setOnClickListener { onAction?.invoke() }
        view.findViewById<Button>(R.id.update_later).visibility = if (busy && action == null) View.GONE else View.VISIBLE
    }

    private fun progress(pct: Int, total: Long) {
        val bar = overlay?.findViewById<ProgressBar>(R.id.update_progress) ?: return
        bar.isIndeterminate = pct < 0
        if (pct >= 0) bar.progress = pct
        overlay?.findViewById<TextView>(R.id.update_text)?.text =
            activity.getString(R.string.update_downloading, megabytes(total))
    }

    private fun askPermission(release: Release, file: File) {
        waiting = release to file
        state(release, activity.getString(R.string.update_permission), busy = false, action = activity.getString(R.string.update_allow)) {
            runCatching {
                activity.startActivity(
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${activity.packageName}"))
                )
            }
        }
    }

    private fun fail(message: String) {
        prefs.edit().putLong("checked", 0L).apply()            // в следующий раз проверим сразу
        state(null, activity.getString(R.string.update_failed, message), busy = false,
            action = activity.getString(R.string.update_retry)) {
            hide()
            onResume()
        }
    }

    private fun hide() {
        val view = overlay ?: return
        overlay = null
        view.animate().alpha(0f).setDuration(180).withEndAction { host.removeView(view) }.start()
    }

    private fun megabytes(bytes: Long) =
        if (bytes > 0) "%.1f МБ".format(bytes / 1_048_576.0) else "…"

    private companion object {
        const val CHECK_EVERY = 30 * 60 * 1000L
        const val MAX_SIZE = 80L * 1024 * 1024
    }
}
