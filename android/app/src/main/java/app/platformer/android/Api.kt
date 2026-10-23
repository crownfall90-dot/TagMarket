package app.platformer.android

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Сервер Platformer: адрес API считается от адреса Mini App так же, как в web/app.js ('../api'). */
object Api {
    class HttpError(val status: Int, message: String) : IOException(message)

    /** Событие из колокольчика приложения. */
    class Event(val id: Long, val title: String, val body: String, val read: Boolean)

    val configured: Boolean get() = BuildConfig.BASE_URL.startsWith("https://")

    private fun endpoint(path: String): URL = URL(URL(BuildConfig.BASE_URL), "../api$path")

    /** Обменять код из бота (/app) на токен устройства. */
    fun pair(code: String, deviceName: String): String {
        val body = JSONObject().put("code", code).put("name", deviceName)
        return post("/device/pair", body, token = null).getString("token")
    }

    /** Шаги по дням: [{day, steps}] → /api/activity/sync с токеном устройства. */
    fun sendSteps(token: String, days: List<Pair<String, Long>>) {
        val list = JSONArray()
        days.forEach { (day, steps) -> list.put(JSONObject().put("day", day).put("steps", steps)) }
        post("/activity/sync", JSONObject().put("days", list), token)
    }

    /** Последние события пользователя (как колокольчик в приложении). */
    fun notifications(token: String): List<Event> {
        val items = request("GET", "/notifications", null, token).optJSONArray("items") ?: return emptyList()
        return (0 until items.length()).mapNotNull { i ->
            val item = items.optJSONObject(i) ?: return@mapNotNull null
            Event(
                item.optLong("id"), item.optString("title").ifBlank { "Platformer" },
                item.optString("body"), !item.isNull("read_at"),
            )
        }.filter { it.id > 0 }
    }

    private fun post(path: String, body: JSONObject, token: String?): JSONObject = request("POST", path, body, token)

    private fun request(method: String, path: String, body: JSONObject?, token: String?): JSONObject {
        val connection = endpoint(path).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 15_000
            connection.readTimeout = 20_000
            if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val json = runCatching { JSONObject(text) }.getOrElse { JSONObject() }
            if (status !in 200..299) {
                throw HttpError(status, json.optString("error").ifBlank { "Сервер ответил $status" })
            }
            return json
        } finally {
            connection.disconnect()
        }
    }
}
