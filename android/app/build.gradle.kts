import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Адрес Mini App (тот же, что MINI_APP_URL на сервере) и бот, который выдаёт код входа.
// Задаются в android/local.properties (platformer.url=…) или переменными окружения
// PLATFORMER_URL / PLATFORMER_BOT — в CI это переменные репозитория.
val local = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
fun setting(key: String, env: String, default: String) =
    (local.getProperty(key) ?: System.getenv(env))?.takeIf { it.isNotBlank() } ?: default

val platformerUrl = setting("platformer.url", "PLATFORMER_URL", "https://crownfail.shop/tagmarkets/app/")
val platformerBot = setting("platformer.bot", "PLATFORMER_BOT", "tagmarketgold_bot")
// Откуда сборка «direct» (APK не из Google Play) узнаёт о новой версии: latest.json из
// релиза android-latest на GitHub — его после каждого слияния в main обновляет CI
val platformerUpdates = setting(
    "platformer.updates", "PLATFORMER_UPDATES",
    "https://github.com/crownfall90-dot/TagMarket/releases/download/android-latest/latest.json"
)

// Firebase Cloud Messaging (мгновенные уведомления): настройки из google-services.json —
// переменная PLATFORMER_FIREBASE (содержимое файла, в CI — переменная репозитория) или файл
// app/google-services.json (не в репозитории). Нет настроек — приложение собирается без
// мгновенных уведомлений и проверяет события раз в 15 минут.
val firebase: Map<String, String> = run {
    val text = System.getenv("PLATFORMER_FIREBASE")?.takeIf { it.isNotBlank() }
        ?: file("google-services.json").takeIf { it.exists() }?.readText()
        ?: return@run emptyMap()
    @Suppress("UNCHECKED_CAST")
    val json = groovy.json.JsonSlurper().parseText(text) as Map<String, Any?>
    val project = json["project_info"] as? Map<String, Any?> ?: return@run emptyMap()
    val client = (json["client"] as? List<Map<String, Any?>>).orEmpty().firstOrNull { c ->
        val info = c["client_info"] as? Map<String, Any?>
        (info?.get("android_client_info") as? Map<String, Any?>)?.get("package_name") == "app.platformer.android"
    } ?: return@run emptyMap()
    val info = client["client_info"] as Map<String, Any?>
    val key = (client["api_key"] as? List<Map<String, Any?>>)?.firstOrNull()?.get("current_key")
    mapOf(
        "APP_ID" to info["mobilesdk_app_id"].toString(),
        "API_KEY" to key.toString(),
        "PROJECT_ID" to project["project_id"].toString(),
        "SENDER_ID" to project["project_number"].toString(),
    )
}

// Подпись для Google Play: ключ загрузки из переменных окружения CI (никогда не в репозитории)
val keystoreFile = System.getenv("PLATFORMER_KEYSTORE")?.let { file(it) }?.takeIf { it.exists() }

android {
    namespace = "app.platformer.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.platformer.android"
        minSdk = 26                 // Health Connect работает с Android 8
        targetSdk = 36              // требование Google Play к новым приложениям
        // в CI — 100 + номер запуска сборки: каждая новая версия выше предыдущей
        versionCode = (System.getenv("PLATFORMER_VERSION_CODE") ?: "100").toInt()
        versionName = System.getenv("PLATFORMER_VERSION_NAME") ?: "0.3.0"
        buildConfigField("String", "BASE_URL", "\"$platformerUrl\"")
        buildConfigField("String", "BOT_USERNAME", "\"$platformerBot\"")
        for (name in listOf("APP_ID", "API_KEY", "PROJECT_ID", "SENDER_ID")) {
            buildConfigField("String", "FCM_$name", "\"${firebase[name].orEmpty()}\"")
        }
    }

    signingConfigs {
        if (keystoreFile != null) {
            create("upload") {
                storeFile = keystoreFile
                storePassword = System.getenv("PLATFORMER_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("PLATFORMER_KEY_ALIAS")
                keyPassword = System.getenv("PLATFORMER_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystoreFile != null) signingConfig = signingConfigs.getByName("upload")
        }
    }

    // direct — APK для установки напрямую, обновляется сам из релизов GitHub;
    // play — для Google Play: обновления только через Play (свои APK Play запрещает качать)
    flavorDimensions += "store"
    productFlavors {
        create("direct") {
            dimension = "store"
            buildConfigField("String", "UPDATE_URL", "\"$platformerUpdates\"")
        }
        create("play") {
            dimension = "store"
            buildConfigField("String", "UPDATE_URL", "\"\"")
        }
    }

    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-ktx:1.11.0")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("com.google.firebase:firebase-messaging:24.1.2")
    // Firebase и app-update тянут старый Fragment 1.1 — с ним ActivityResult API работает неверно
    implementation("androidx.fragment:fragment-ktx:1.8.9")
    "playImplementation"("com.google.android.play:app-update-ktx:2.1.0")

}
