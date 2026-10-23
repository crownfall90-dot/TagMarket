package app.platformer.android

import android.content.Context
import android.os.Bundle
import android.widget.Button
import androidx.activity.ComponentActivity

/** Зачем Platformer шаги — Health Connect показывает это по кнопке «Подробнее». */
class HealthRationaleActivity : ComponentActivity() {
    /** Цвета экрана — по теме, выбранной в Platformer (тёмная или светлая). */
    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(newBase)
        applyOverrideConfiguration(AppTheme.override(newBase))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_rationale)
        findViewById<Button>(R.id.close).setOnClickListener { finish() }
    }
}
