package app.platformer.android

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
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

        val root = FrameLayout(this).apply { setBackgroundColor(Color.parseColor("#0f1214")) }
        web = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#0f1214"))
            overScrollMode = View.OVER_SCROLL_NEVER
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.userAgentString = settings.userAgentString + " PlatformerAndroid/" + BuildConfig.VERSION_NAME
            addJavascriptInterface(WebBridge(store) { runOnUiThread { signOut() } }, "PlatformerAndroid")
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
        // контент — между системными панелями: страница сама рисует фон под ними
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
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

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (!request.isForMainFrame) return
            loaded = true
            view.loadDataWithBaseURL(
                null, OFFLINE_PAGE.replace("{retry}", startUrl()), "text/html", "utf-8", null
            )
        }
    }

    private companion object {
        const val OFFLINE_PAGE = """<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1214;color:#e8ece6;font:16px system-ui,sans-serif;text-align:center}
b{display:block;font-size:22px;margin-bottom:8px}p{color:#8e9a92;margin:0 24px 22px}a{display:inline-block;padding:13px 22px;border-radius:14px;background:#c8f08f;color:#22301b;text-decoration:none;font-weight:600}</style>
</head><body><div><b>Нет соединения</b><p>Platformer откроется, как только появится интернет.</p><a href="{retry}">Повторить</a></div></body></html>"""
    }
}
