package app.platformer.android

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Вход: код из бота (/app) → токен устройства. Без логинов и паролей. */
class LoginActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_login)
        val root = findViewById<View>(R.id.login_root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }

        val code = findViewById<EditText>(R.id.code)
        val enter = findViewById<Button>(R.id.enter)
        val error = findViewById<TextView>(R.id.error)
        val openBot = findViewById<Button>(R.id.open_bot)

        if (!Api.configured) {
            error.text = getString(R.string.login_not_configured)
            error.visibility = View.VISIBLE
            enter.isEnabled = false
        }

        openBot.setOnClickListener {
            val bot = BuildConfig.BOT_USERNAME
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://t.me/$bot"))) }
        }

        fun submit() {
            val value = code.text.toString().trim()
            if (value.length < 8) {
                error.text = getString(R.string.login_short)
                error.visibility = View.VISIBLE
                return
            }
            enter.isEnabled = false
            error.visibility = View.GONE
            lifecycleScope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching { Api.pair(value, "${Build.MANUFACTURER} ${Build.MODEL}".trim()) }
                }
                result.onSuccess { token ->
                    TokenStore(this@LoginActivity).token = token
                    startActivity(Intent(this@LoginActivity, MainActivity::class.java))
                    finish()
                }.onFailure { e ->
                    error.text = e.message ?: getString(R.string.login_failed)
                    error.visibility = View.VISIBLE
                    enter.isEnabled = true
                }
            }
        }

        enter.setOnClickListener { submit() }
        code.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_DONE) { submit(); true } else false
        }
    }
}
