package app.platformer.android

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
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
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Самообновление APK, установленного не из Google Play. При запуске (и не чаще раза
 * в 30 минут при возвращении) читает latest.json из релиза на GitHub. Если версия
 * новее — показывает окно: номер версии, что нового и кнопку «Обновить до …».
 * Обновление обязательное: пока окно на экране, приложением пользоваться нельзя.
 * По кнопке качает APK, сверяет SHA-256, имя пакета, номер версии и подпись с
 * установленным приложением и ставит его через PackageInstaller. На Android 12+
 * обновление самого себя проходит без вопросов; на старых — одно «Установить».
 */
class Updater(private val activity: ComponentActivity, private val host: FrameLayout) {
    private class Release(
        val code: Long, val name: String, val apk: String, val sha256: String, val size: Long, val notes: List<String>,
    )

    private val prefs = activity.getSharedPreferences("updates", Context.MODE_PRIVATE)
    private var job: Job? = null
    private var overlay: View? = null
    private var waiting: Pair<Release, File>? = null       // скачано, ждём разрешения на установку
    private var offered: Release? = null
    private var netCallback: ConnectivityManager.NetworkCallback? = null
    private var launched = true                             // при открытии приложения проверяем всегда

    init {
        UpdateReceiver.listener = { status, message -> activity.runOnUiThread { onStatus(status, message) } }
    }

    /** Новая версия найдена и ещё не установлена — приложение закрыто окном обновления. */
    val blocking get() = overlay != null

    private class WrongSignature : Exception("подпись не совпадает")

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
                if (release.code > BuildConfig.VERSION_CODE) offer(release)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // нет интернета — говорим прямо: без проверки войти нельзя; другие сбои (релиза ещё
                // нет, GitHub недоступен) не мешают пользоваться приложением
                if (offline(e)) showOffline()
            }
        }
    }

    private fun offline(e: Exception): Boolean {
        if (e is UnknownHostException || e is ConnectException || e is SocketTimeoutException || e is NoRouteToHostException) return true
        val cm = activity.getSystemService(ConnectivityManager::class.java) ?: return false
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return true
        return !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /** «Нет интернета»: окно с кнопкой «Повторить»; сеть появилась — проверяем сами. */
    private fun showOffline() {
        if (overlay == null) {
            show(null)
        }
        val view = overlay ?: return
        view.findViewById<TextView>(R.id.update_eyebrow).text = activity.getString(R.string.update_offline_eyebrow)
        view.findViewById<TextView>(R.id.update_title).text = activity.getString(R.string.update_offline_title)
        notesVisible(false)
        state(null, activity.getString(R.string.update_offline), busy = false, action = activity.getString(R.string.update_retry)) {
            retryCheck()
        }
        if (netCallback == null) {
            val cm = activity.getSystemService(ConnectivityManager::class.java) ?: return
            val callback = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    activity.runOnUiThread { retryCheck() }
                }
            }
            runCatching { cm.registerDefaultNetworkCallback(callback) }.onSuccess { netCallback = callback }
        }
    }

    private fun retryCheck() {
        if (job?.isActive == true) return
        stopWatchingNetwork()
        overlay?.let { state(null, activity.getString(R.string.update_checking), busy = true) }
        launched = true
        job = activity.lifecycleScope.launch {
            try {
                val release = withContext(Dispatchers.IO) { fetch() }
                prefs.edit().putLong("checked", System.currentTimeMillis()).apply()
                if (release.code > BuildConfig.VERSION_CODE) offer(release) else hide()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (offline(e)) showOffline() else hide()
            } finally {
                launched = false
            }
        }
    }

    private fun stopWatchingNetwork() {
        val callback = netCallback ?: return
        netCallback = null
        runCatching { activity.getSystemService(ConnectivityManager::class.java)?.unregisterNetworkCallback(callback) }
    }

    /** Окно «Доступно обновление»: версия, что нового и «Обновить до …». */
    private fun offer(release: Release) {
        stopWatchingNetwork()
        show(release)
        overlay?.findViewById<TextView>(R.id.update_eyebrow)?.text = activity.getString(R.string.update_eyebrow)
        val view = overlay ?: return
        val notes = release.notes.ifEmpty { listOf(activity.getString(R.string.update_no_notes)) }
        view.findViewById<TextView>(R.id.update_notes).text = notes.joinToString("\n") { "•  $it" }
        notesVisible(true)
        state(release, activity.getString(R.string.update_current, BuildConfig.VERSION_NAME), busy = false,
            action = activity.getString(R.string.update_now, release.name.ifBlank { release.code.toString() })) {
            start(release)
        }
    }

    /** Нажали «Обновить»: качаем, проверяем и ставим. */
    private fun start(release: Release) {
        job?.cancel()
        notesVisible(false)
        state(release, activity.getString(R.string.update_downloading, megabytes(release.size)), busy = true)
        job = activity.lifecycleScope.launch {
            try {
                val file = withContext(Dispatchers.IO) { download(release) }
                withContext(Dispatchers.IO) { verify(release, file) }
                if (canInstall()) install(release, file) else askPermission(release, file)
            } catch (e: CancellationException) {
                throw e
            } catch (_: WrongSignature) {
                reinstall(release)
            } catch (e: Exception) {
                fail(release, e.message ?: e.javaClass.simpleName)
            }
        }
    }

    /** Эта копия подписана другим ключом: поверх неё обновление не встанет — только переустановка. */
    private fun reinstall(release: Release) {
        notesVisible(false)
        state(release, activity.getString(R.string.update_reinstall), busy = false,
            action = activity.getString(R.string.update_download)) {
            runCatching { activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(release.apk))) }
        }
    }

    private fun notesVisible(on: Boolean) {
        val v = if (on) View.VISIBLE else View.GONE
        overlay?.findViewById<View>(R.id.update_notes_title)?.visibility = v
        overlay?.findViewById<View>(R.id.update_notes)?.visibility = v
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
            val notes = json.optJSONArray("notes")?.let { arr ->
                (0 until arr.length()).map { arr.optString(it).trim().take(160) }.filter { it.isNotEmpty() }.take(8)
            }.orEmpty()
            return Release(json.getLong("versionCode"), json.optString("versionName"), apk, sha, json.optLong("size"), notes)
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
            throw WrongSignature()
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
                fail(release, e.message ?: e.javaClass.simpleName)
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
            // нажали «Отмена» в окне Android — обновление обязательное, предлагаем снова
            PackageInstaller.STATUS_FAILURE_ABORTED -> offered?.let { offer(it) }
            else -> fail(offered, message ?: "ошибка $status")
        }
    }

    // ── окно ─────────────────────────────────────────────────────────────

    private fun show(release: Release?) {
        if (overlay == null) {
            val view = LayoutInflater.from(activity).inflate(R.layout.view_update, host, false)
            host.addView(view)
            // карточка — над панелью жестов и под статус-баром на любом экране
            ViewCompat.getRootWindowInsets(host)?.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
            )?.let { bars ->
                val own = (host.paddingBottom > 0)            // экран уже отступил от панелей сам
                if (!own) view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            }
            val card = view.findViewById<View>(R.id.update_card)
            view.alpha = 0f
            card.translationY = 80f * activity.resources.displayMetrics.density
            view.animate().alpha(1f).setDuration(220).start()
            card.animate().translationY(0f).setDuration(320).start()
            overlay = view
        }
        if (release == null) return
        offered = release
        overlay!!.findViewById<TextView>(R.id.update_title).text =
            activity.getString(R.string.update_title, release.name.ifBlank { release.code.toString() })
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
        view.findViewById<Button>(R.id.update_later).visibility = View.GONE   // обновление обязательное
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

    private fun fail(release: Release?, message: String) {
        prefs.edit().putLong("checked", 0L).apply()            // в следующий раз проверим сразу
        if (overlay == null && release != null) show(release)
        notesVisible(false)
        state(null, activity.getString(R.string.update_failed, message), busy = false,
            action = activity.getString(R.string.update_retry)) {
            if (release != null) start(release) else hide()
        }
    }

    private fun hide() {
        stopWatchingNetwork()
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
