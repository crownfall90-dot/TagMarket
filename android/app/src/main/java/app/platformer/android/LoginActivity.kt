package app.platformer.android

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.InputFilter
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.animation.DecelerateInterpolator
import android.view.animation.OvershootInterpolator
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.children
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Вход без логинов и паролей: «Запросить код» открывает бота в Telegram, бот сразу
 * присылает код с кнопкой «Скопировать». Вернулись в приложение — скопированный код
 * подставляется и отправляется сам. Код вводится обязательно: так войти может только
 * тот, кто видит ваш чат с ботом.
 */
class LoginActivity : ComponentActivity() {
    private lateinit var code: EditText
    private lateinit var cells: List<TextView>
    private lateinit var cellRow: ViewGroup
    private lateinit var enter: Button
    private lateinit var error: TextView
    private var lastAutoCode: String? = null
    // код подставляем из буфера только после «Запросить код» и только новый:
    // то, что лежало в буфере в момент запроса (старый код), не трогаем
    private var requested = false
    private var staleClip: String? = null
    private var busy = false
    private var updater: Updater? = null

    /** Цвета экрана — по теме, выбранной в Platformer (тёмная или светлая). */
    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(newBase)
        applyOverrideConfiguration(AppTheme.override(newBase))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        savedInstanceState?.let {
            requested = it.getBoolean(KEY_REQUESTED)
            staleClip = it.getString(KEY_STALE)
            lastAutoCode = it.getString(KEY_LAST)
        }
        enableEdgeToEdge()
        setContentView(R.layout.activity_login)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.login_scroll)) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime()
            )
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }

        // на планшете и в альбомной ориентации форма не растягивается во всю ширину
        val content = findViewById<ViewGroup>(R.id.login_content)
        if (resources.configuration.screenWidthDp > 520) {
            content.layoutParams = (content.layoutParams as FrameLayout.LayoutParams).apply {
                width = dp(480f).toInt()
                gravity = Gravity.CENTER_HORIZONTAL
            }
        }

        code = findViewById(R.id.code)
        cellRow = findViewById(R.id.cells)
        cells = cellRow.children.filterIsInstance<TextView>().toList()
        enter = findViewById(R.id.enter)
        error = findViewById(R.id.error)
        val requestCode = findViewById<View>(R.id.request_code)
        val requestLabel = findViewById<TextView>(R.id.request_label)
        val sent = findViewById<TextView>(R.id.sent)

        if (!Api.configured) {
            showError(getString(R.string.login_not_configured))
            enter.isEnabled = false
        }

        requestCode.setOnClickListener {
            staleClip = clipCode()
            requested = true
            val bot = BuildConfig.BOT_USERNAME
            // сначала приложение Telegram напрямую, если его нет — ссылка t.me в браузере
            val opened = runCatching {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("tg://resolve?domain=$bot&start=login")))
            }.isSuccess || runCatching {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://t.me/$bot?start=login")))
            }.isSuccess
            if (opened) {
                requestLabel.text = getString(R.string.login_request_again)
                if (sent.visibility != View.VISIBLE) {
                    sent.alpha = 0f
                    sent.translationY = -dp(6f)
                    sent.visibility = View.VISIBLE
                    sent.animate().alpha(1f).translationY(0f).setDuration(260).start()
                }
            }
        }

        code.filters = arrayOf(InputFilter.AllCaps(), InputFilter.LengthFilter(9))
        code.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: Editable?) {
                if (error.visibility == View.VISIBLE && Api.configured) error.visibility = View.GONE
                renderCells(false)
                if (value().length == 8) submit()
            }
        })
        code.setOnFocusChangeListener { _, _ -> renderCells(false) }
        code.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_DONE) { submit(); true } else false
        }
        enter.setOnClickListener { submit() }
        renderCells(false)
        intro(findViewById(R.id.login_content))
        // новая версия — обязательна: окно обновления закрывает и экран входа
        updater = Updater(this, findViewById(R.id.login_root))
    }

    /** Код без дефиса и лишних символов. */
    private fun value() = code.text.toString().uppercase().filter { it in 'A'..'Z' || it in '2'..'9' }.take(8)

    private fun renderCells(failed: Boolean) {
        val text = value()
        val focused = code.hasFocus()
        cells.forEachIndexed { i, cell ->
            val ch = text.getOrNull(i)
            cell.text = ch?.toString() ?: ""
            if (failed) {
                cell.setBackgroundResource(R.drawable.bg_cell_error)
            } else {
                cell.setBackgroundResource(R.drawable.bg_cell)
                cell.isActivated = ch != null
                cell.isSelected = focused && i == text.length.coerceAtMost(7)
            }
        }
    }

    private fun showError(message: String) {
        error.text = message
        error.visibility = View.VISIBLE
    }

    private fun submit() {
        if (busy) return
        val value = value()
        if (value.length < 8) {
            showError(getString(R.string.login_short))
            shake()
            return
        }
        busy = true
        enter.isEnabled = false
        enter.text = getString(R.string.login_entering)
        error.visibility = View.GONE
        (getSystemService(INPUT_METHOD_SERVICE) as? InputMethodManager)?.hideSoftInputFromWindow(code.windowToken, 0)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { Api.pair(value, "${Build.MANUFACTURER} ${Build.MODEL}".trim()) }
            }
            result.onSuccess { token ->
                TokenStore(this@LoginActivity).token = token
                startActivity(Intent(this@LoginActivity, MainActivity::class.java))
                overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
                finish()
            }.onFailure { e ->
                busy = false
                enter.isEnabled = true
                enter.text = getString(R.string.login_enter)
                showError(e.message ?: getString(R.string.login_failed))
                renderCells(true)
                shake()
            }
        }
    }

    /** Ячейки качаются из стороны в сторону — код не подошёл. */
    private fun shake() {
        val d = dp(8f)
        cellRow.animate().cancel()
        cellRow.translationX = 0f
        cellRow.animate().translationX(d).setDuration(50).withEndAction {
            cellRow.animate().translationX(-d).setDuration(90).withEndAction {
                cellRow.animate().translationX(d / 2).setDuration(80).withEndAction {
                    cellRow.animate().translationX(0f).setDuration(70).start()
                }.start()
            }.start()
        }.start()
    }

    /** Плавное появление: логотип с лёгким «пружинящим» масштабом, остальное — снизу вверх по очереди. */
    private fun intro(content: ViewGroup) {
        content.children.forEachIndexed { i, child ->
            child.alpha = 0f
            child.translationY = dp(16f)
            if (i == 0) { child.scaleX = 0.8f; child.scaleY = 0.8f }
            child.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
                .setStartDelay(60L * i).setDuration(420)
                .setInterpolator(if (i == 0) OvershootInterpolator(1.6f) else DecelerateInterpolator(2f))
                .start()
        }
    }

    override fun onResume() {
        super.onResume()
        updater?.onResume()
    }

    private fun dp(v: Float) = v * resources.displayMetrics.density

    /** Код входа из буфера обмена или null. */
    private fun clipCode(): String? {
        val clip = (getSystemService(CLIPBOARD_SERVICE) as? ClipboardManager)?.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        val text = clip.getItemAt(0).coerceToText(this)?.toString()?.trim()?.uppercase() ?: return null
        return text.takeIf { CODE.matches(it) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(KEY_REQUESTED, requested)
        outState.putString(KEY_STALE, staleClip)
        outState.putString(KEY_LAST, lastAutoCode)
    }

    /** Запросили код и вернулись из Telegram с новым кодом в буфере — подставляем и входим сами. */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus || !requested || !::code.isInitialized || busy) return
        val text = clipCode() ?: return
        if (text == staleClip || text == lastAutoCode) return
        lastAutoCode = text
        code.setText(text)              // восемь символов → вход запускается сам
        code.setSelection(code.text.length)
    }

    private companion object {
        val CODE = Regex("^[A-Z2-9]{4}-?[A-Z2-9]{4}$")
        const val KEY_REQUESTED = "requested"
        const val KEY_STALE = "stale_clip"
        const val KEY_LAST = "last_code"
    }
}
