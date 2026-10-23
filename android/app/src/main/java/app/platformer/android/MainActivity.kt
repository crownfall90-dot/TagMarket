package app.platformer.android

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.RenderProcessGoneDetail
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.graphics.ColorUtils
import androidx.core.view.HapticFeedbackConstantsCompat
import androidx.core.view.WindowCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Platformer в оболочке Android: веб-интерфейс Mini App + вход по коду и шаги из Health Connect. */
class MainActivity : ComponentActivity() {
    private lateinit var store: TokenStore
    private lateinit var web: WebView
    private var updater: Updater? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var loaded = false

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data))
        fileCallback = null
    }

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) Alerts.schedule(this)
        refreshPermissions()
    }

    private val askActivity = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        lifecycleScope.launch {
            if (granted && StepRecorder.subscribe(this@MainActivity)) {
                Steps.schedule(this@MainActivity)
                Steps.syncNow(this@MainActivity)
            }
            refreshPermissions()
            offerHealth()
        }
    }

    private val askHealth = registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
        if (granted.isNotEmpty()) {
            Steps.schedule(this)
            lifecycleScope.launch { Steps.syncNow(this@MainActivity) }
        }
        refreshPermissions()
    }

    /** Цвета экрана — по теме, выбранной в Platformer (тёмная или светлая). */
    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(newBase)
        applyOverrideConfiguration(AppTheme.override(newBase))
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen().setKeepOnScreenCondition { !loaded && ::web.isInitialized }
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        store = TokenStore(this)
        if (store.token == null || !Api.configured) {
            openLogin()
            return
        }

        val bg = AppTheme.background(this)
        val root = FrameLayout(this).apply { setBackgroundColor(bg) }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web = WebView(this).apply {
            setBackgroundColor(bg)
            overScrollMode = View.OVER_SCROLL_NEVER
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            with(settings) {
                javaScriptEnabled = true
                domStorageEnabled = true
                allowFileAccess = false
                allowContentAccess = false
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                setGeolocationEnabled(false)
                javaScriptCanOpenWindowsAutomatically = false
                setSupportMultipleWindows(false)
                setSupportZoom(false)
                builtInZoomControls = false
                displayZoomControls = false
                mediaPlaybackRequiresUserGesture = true
                // крупный системный шрифт уважаем, но в разумных пределах — иначе вёрстка ломается
                textZoom = (resources.configuration.fontScale * 100).toInt().coerceIn(85, 120)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) safeBrowsingEnabled = true
                userAgentString = userAgentString + " PlatformerAndroid/" + BuildConfig.VERSION_NAME
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, true)
            }
            addJavascriptInterface(
                WebBridge(
                    store,
                    onSignOut = { runOnUiThread { signOut() } },
                    onHaptic = { kind -> runOnUiThread { haptic(kind) } },
                    onTheme = { color -> runOnUiThread { root.setBackgroundColor(color); setBackgroundColor(color); barIcons(color); AppTheme.remember(this@MainActivity, color) } },
                    onPermissions = { permissionsJson() },
                    onFix = { kind -> runOnUiThread { fixPermission(kind) } },
                    onShare = { text -> runOnUiThread { shareText(text) } },
                    onCopy = { text -> runOnUiThread { copyText(text) } },
                ),
                "PlatformerAndroid",
            )
            webViewClient = PlatformerClient()
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                    fileCallback?.onReceiveValue(null)
                    fileCallback = callback
                    return runCatching { pickFiles.launch(params.createIntent()) }.isSuccess.also { ok ->
                        if (!ok) fileCallback = null
                    }
                }
            }
        }
        root.addView(web, FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        setContentView(root)
        updater = Updater(this, root)
        // контент — между системными панелями и вырезом камеры; фон под ними — цвет темы страницы
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime()
            )
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (updater?.blocking == true) { finish(); return }      // обновление обязательное
                if (updater?.back() == true) return                       // «Назад» у окна с «Позже» — позже
                // сначала страница: открытое окно или меню закрываются «Назад», как в обычном приложении
                web.evaluateJavascript("window.platformerBack ? window.platformerBack() : false") { handled ->
                    if (handled == "true") return@evaluateJavascript
                    if (web.canGoBack()) web.goBack() else finish()
                }
            }
        })

        if (savedInstanceState != null) web.restoreState(savedInstanceState) else web.loadUrl(startUrl())
        offerSteps()
        offerAlerts()
        // пока приложение на экране — шаги уходят каждую минуту, и кольцо «Шаги» живое;
        // в фоне их раз в 15 минут отправляет WorkManager
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    Steps.syncNow(this@MainActivity)
                    delay(60_000)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        updater?.onResume()                 // вход в приложение — новая версия обязательна; пока открыто, ищет сам
        refreshPermissions()                // вернулись из настроек — строка «Шаги» в настройках обновится
        if (::web.isInitialized) lifecycleScope.launch {
            if (StepRecorder.ready(this@MainActivity)) StepRecorder.subscribe(this@MainActivity)
            if (Steps.anySource(this@MainActivity)) Steps.schedule(this@MainActivity)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::web.isInitialized) web.saveState(outState)
    }

    private fun startUrl(): String = Uri.parse(BuildConfig.BASE_URL).buildUpon()
        .appendQueryParameter("app", "android").build().toString()

    @Volatile
    private var stepsAccess = "unavailable"

    @Volatile
    private var healthAccess = "unavailable"

    private fun permissionsJson(): String =
        org.json.JSONObject().put("steps", stepsAccess).put("health", healthAccess).put("notifications", Alerts.allowed(this)).toString()

    /** Перечитать доступы и сказать странице — она перерисует строки в настройках. */
    private fun refreshPermissions() {
        if (!::web.isInitialized) return
        lifecycleScope.launch {
            stepsAccess = when {
                Steps.anySource(this@MainActivity) -> "granted"
                !Steps.available(this@MainActivity) && !StepRecorder.available(this@MainActivity) -> "unavailable"
                else -> "denied"
            }
            healthAccess = when {
                !Steps.available(this@MainActivity) -> "unavailable"
                Steps.healthGranted(this@MainActivity) -> "granted"
                else -> "denied"
            }
            web.evaluateJavascript("window.onPlatformerPermissions && window.onPlatformerPermissions()", null)
        }
    }

    /** «Включить» в настройках: сначала системный вопрос, если Android больше не спрашивает — экран настроек. */
    private fun fixPermission(kind: String) {
        if (kind == "health") {
            if (!Steps.available(this)) {
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.apps.healthdata"))) }
                return
            }
            val prefs = getSharedPreferences("perm_fix", MODE_PRIVATE)
            if (!prefs.getBoolean("health_asked", false)) {
                prefs.edit().putBoolean("health_asked", true).apply()
                askHealth.launch(Steps.permissions(this))
            } else {
                runCatching { startActivity(Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)) }
                    .onFailure { askHealth.launch(Steps.permissions(this)) }
            }
            return
        }
        if (kind == "steps") {
            // сначала счётчик телефона — он ближе всего к встроенному трекеру
            if (StepRecorder.available(this) && !StepRecorder.permitted(this)) {
                val asked = getSharedPreferences("perm_fix", MODE_PRIVATE).getBoolean("activity_asked", false)
                if (!asked || shouldShowRequestPermissionRationale(StepRecorder.PERMISSION)) {
                    getSharedPreferences("perm_fix", MODE_PRIVATE).edit().putBoolean("activity_asked", true).apply()
                    askActivity.launch(StepRecorder.PERMISSION)
                } else {
                    runCatching {
                        startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                    }
                }
                return
            }
            if (!Steps.available(this)) {
                runCatching {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.apps.healthdata")))
                }
                return
            }
            val prefs = getSharedPreferences("perm_fix", MODE_PRIVATE)
            if (!prefs.getBoolean("steps_asked", false)) {
                prefs.edit().putBoolean("steps_asked", true).apply()
                askHealth.launch(Steps.permissions(this))
            } else {
                runCatching { startActivity(Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)) }
                    .onFailure { askHealth.launch(Steps.permissions(this)) }
            }
        } else {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED &&
                shouldShowRequestPermissionRationale(android.Manifest.permission.POST_NOTIFICATIONS)
            ) {
                askNotifications.launch(android.Manifest.permission.POST_NOTIFICATIONS)
            } else {
                runCatching {
                    startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                        .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, packageName))
                }
            }
        }
    }

    private fun shareText(text: String) {
        val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
        runCatching { startActivity(Intent.createChooser(send, getString(R.string.share_title))) }
    }

    private fun copyText(text: String) {
        val clipboard = getSystemService(CLIPBOARD_SERVICE) as? android.content.ClipboardManager ?: return
        clipboard.setPrimaryClip(android.content.ClipData.newPlainText("Platformer", text))
    }

    /** Уведомления о событиях: на Android 13+ спросим разрешение один раз, дальше — как решил человек. */
    private fun offerAlerts() {
        Alerts.schedule(this)
        Push.register(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !Alerts.allowed(this)) {
            val prefs = getSharedPreferences("alerts_ask", MODE_PRIVATE)
            if (!prefs.getBoolean("asked", false)) {
                prefs.edit().putBoolean("asked", true).apply()
                askNotifications.launch(android.Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    override fun onStart() {
        super.onStart()
        Alerts.foreground = true
    }

    override fun onStop() {
        Alerts.foreground = false
        super.onStop()
    }

    /** Шаги из Health Connect — спросим один раз; отказ уважаем, повторно не навязываем. */
    /**
     * Шаги: сначала счётчик телефона (разрешение «Физическая активность»), затем Health Connect.
     * Каждое разрешение спрашиваем один раз; отказ уважаем — включить можно в «Доступах телефона».
     */
    private fun offerSteps() {
        lifecycleScope.launch {
            if (StepRecorder.ready(this@MainActivity)) {
                StepRecorder.subscribe(this@MainActivity)
                Steps.schedule(this@MainActivity)
            }
            val prefs = getSharedPreferences("perm_fix", MODE_PRIVATE)
            if (StepRecorder.available(this@MainActivity) && !StepRecorder.permitted(this@MainActivity) &&
                !prefs.getBoolean("activity_asked", false)
            ) {
                prefs.edit().putBoolean("activity_asked", true).apply()
                askActivity.launch(StepRecorder.PERMISSION)     // Health Connect спросим после ответа
                return@launch
            }
            offerHealth()
        }
    }

    /**
     * Health Connect: шаги, сон и пульс. Спрашиваем один раз; тем, кто раньше разрешил только
     * шаги, — ещё один раз, уже про сон и пульс. Дальше включить можно в «Доступах телефона».
     */
    private fun offerHealth() {
        if (!Steps.available(this)) return
        lifecycleScope.launch {
            val granted = Steps.grantedSet(this@MainActivity)
            if (granted.isNotEmpty()) Steps.schedule(this@MainActivity)
            val missing = Steps.permissions(this@MainActivity) - granted - Steps.BACKGROUND
            val prefs = getSharedPreferences("perm_fix", MODE_PRIVATE)
            if (missing.isNotEmpty() && !prefs.getBoolean("health_asked", false)) {
                prefs.edit().putBoolean("health_asked", true).apply()
                store.askedHealth = true
                askHealth.launch(Steps.permissions(this@MainActivity))
            }
        }
    }

    /** Светлая тема страницы — тёмные значки статус-бара и жестов, тёмная — светлые. */
    private fun barIcons(color: Int) {
        val light = ColorUtils.calculateLuminance(color) > 0.5
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = light
            isAppearanceLightNavigationBars = light
        }
    }

    private fun haptic(kind: String) {
        val type = when (kind) {
            "success" -> HapticFeedbackConstantsCompat.CONFIRM
            "warning", "error" -> HapticFeedbackConstantsCompat.REJECT
            "impact" -> HapticFeedbackConstantsCompat.VIRTUAL_KEY
            else -> HapticFeedbackConstantsCompat.CLOCK_TICK
        }
        ViewCompat.performHapticFeedback(web, type)
    }

    override fun onDestroy() {
        if (::web.isInitialized && web.parent != null) {
            (web.parent as? ViewGroup)?.removeView(web)
            web.destroy()
        }
        super.onDestroy()
    }

    private fun signOut() {
        store.token = null
        Steps.cancel(this)
        Alerts.cancel(this)
        Push.unregister()
        openLogin()
    }

    private fun openLogin() {
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    private inner class PlatformerClient : WebViewClient() {
        private val home = Uri.parse(BuildConfig.BASE_URL).host

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url
            if (url.scheme == "https" && url.host == home) return false
            // Telegram, сайты банков и всё остальное — во внешнем приложении, а не в оболочке
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, url)) }
            return true
        }

        override fun onPageFinished(view: WebView, url: String) {
            loaded = true
        }

        /** Процесс страницы упал или система забрала память — пересоздаём экран, а не роняем приложение. */
        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            (view.parent as? ViewGroup)?.removeView(view)
            view.destroy()
            recreate()
            return true
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (!request.isForMainFrame) return
            loaded = true
            view.loadDataWithBaseURL(
                null, offlinePage(AppTheme.light(this@MainActivity)).replace("{retry}", startUrl()), "text/html", "utf-8", null
            )
        }
    }

    private companion object {
        /** Страница «нет соединения» в цветах темы приложения: тёмной или светлой. */
        fun offlinePage(light: Boolean): String {
            val (bg, card, line, text, muted) =
                if (light) listOf("#f6f5fb", "#ffffff", "#15122b12", "#15122b", "#6c6789")
                else listOf("#0c0a18", "#18142e", "#ffffff14", "#f5f3ff", "#a9a3c9")
            return OFFLINE_PAGE.replace("{bg}", bg).replace("{card}", card).replace("{line}", line)
                .replace("{text}", text).replace("{muted}", muted).replace("{ink}", bg)
        }

        const val OFFLINE_PAGE = """<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:{bg};color:{text};font:16px system-ui,-apple-system,Roboto,sans-serif;text-align:center;-webkit-user-select:none;user-select:none}
.card{width:min(360px,100%);padding:32px 24px;border-radius:26px;background:{card};border:1px solid {line};animation:in .5s cubic-bezier(.2,.9,.3,1) both}
.dot{width:56px;height:56px;margin:0 auto 18px;border-radius:50%;display:grid;place-items:center;background:{line};color:{text};font-size:26px}
b{display:block;font-size:21px;margin-bottom:8px;letter-spacing:-.02em}p{color:{muted};margin:0 0 24px;line-height:1.45}
a{display:block;padding:15px 22px;border-radius:999px;background:{text};color:{ink};text-decoration:none;font-weight:650;transition:transform .15s}a:active{transform:scale(.97)}
@keyframes in{from{opacity:0;transform:translateY(14px)}}@media(prefers-reduced-motion:reduce){.card{animation:none}}</style>
</head><body><div class="card"><div class="dot">⟳</div><b>Нет соединения</b><p>Platformer откроется сам, как только появится интернет.</p><a href="{retry}">Повторить</a></div>
<script>addEventListener('online',function(){location.href=document.querySelector('a').href})</script></body></html>"""
    }
}
