package app.platformer.android

import android.os.Bundle
import android.widget.Button
import androidx.activity.ComponentActivity

/** Зачем Platformer шаги — Health Connect показывает это по кнопке «Подробнее». */
class HealthRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_rationale)
        findViewById<Button>(R.id.close).setOnClickListener { finish() }
    }
}
