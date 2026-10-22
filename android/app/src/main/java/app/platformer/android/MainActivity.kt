package app.platformer.android

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
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
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var loaded = false

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data))
        fileCallback = null
    }

    private val askHealth = registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
        if (Steps.readSteps in granted) Steps.schedule(this)
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

        val root = FrameLayout(this).apply { setBackgroundColor(BG) }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web = WebView(this).apply {
            setBackgroundColor(BG)
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
                    onTheme = { color -> runOnUiThread { root.setBackgroundColor(color); setBackgroundColor(color); barIcons(color) } },
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
                // сначала страница: открытое окно или меню закрываются «Назад», как в обычном приложении
                web.evaluateJavascript("window.platformerBack ? window.platformerBack() : false") { handled ->
                    if (handled == "true") return@evaluateJavascript
                    if (web.canGoBack()) web.goBack() else finish()
                }
            }
        })

        if (savedInstanceState != null) web.restoreState(savedInstanceState) else web.loadUrl(startUrl())
        offerSteps()
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
        if (::web.isInitialized) lifecycleScope.launch { if (Steps.granted(this@MainActivity)) Steps.schedule(this@MainActivity) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::web.isInitialized) web.saveState(outState)
    }

    private fun startUrl(): String = Uri.parse(BuildConfig.BASE_URL).buildUpon()
        .appendQueryParameter("app", "android").build().toString()

    /** Шаги из Health Connect — спросим один раз; отказ уважаем, повторно не навязываем. */
    private fun offerSteps() {
        if (!Steps.available(this)) return
        lifecycleScope.launch {
            if (Steps.granted(this@MainActivity)) {
                Steps.schedule(this@MainActivity)
            } else if (!store.askedHealth) {
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
                null, OFFLINE_PAGE.replace("{retry}", startUrl()), "text/html", "utf-8", null
            )
        }
    }

    private companion object {
        val BG = Color.parseColor("#0B0B0C")
        const val OFFLINE_PAGE = """<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(420px 320px at 85% 0%,#ffffff12,transparent),#0b0b0c;color:#f5f5f6;font:16px system-ui,sans-serif;text-align:center;-webkit-user-select:none;user-select:none}
.card{width:min(360px,100%);padding:32px 24px;border-radius:26px;background:#161618e6;border:1px solid #ffffff14;animation:in .5s cubic-bezier(.2,.9,.3,1) both}
.dot{width:56px;height:56px;margin:0 auto 18px;border-radius:18px;display:grid;place-items:center;background:#ffffff14;color:#f2f2f3;font-size:26px}
b{display:block;font-size:21px;margin-bottom:8px;letter-spacing:-.02em}p{color:#8d8d93;margin:0 0 24px;line-height:1.45}
a{display:block;padding:15px 22px;border-radius:16px;background:linear-gradient(180deg,#fff,#e4e4e7);color:#0b0b0c;text-decoration:none;font-weight:650;transition:transform .15s}a:active{transform:scale(.97)}
@keyframes in{from{opacity:0;transform:translateY(14px)}}@media(prefers-reduced-motion:reduce){.card{animation:none}}</style>
</head><body><div class="card"><div class="dot">⟳</div><b>Нет соединения</b><p>Platformer откроется сам, как только появится интернет.</p><a href="{retry}">Повторить</a></div>
<script>addEventListener('online',function(){location.href=document.querySelector('a').href})</script></body></html>"""
    }
}
