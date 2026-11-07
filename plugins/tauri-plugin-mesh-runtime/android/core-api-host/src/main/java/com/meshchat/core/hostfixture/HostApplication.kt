package com.meshchat.core.hostfixture

import android.app.Application
import android.app.ActivityManager
import android.os.Build
import android.os.Process
import android.util.Base64
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.security.SecureRandom
import org.json.JSONObject

/** CI-only host. Its private app directory and identity never belong to Mesh Chat. */
class HostApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        val process = if (Build.VERSION.SDK_INT >= 28) getProcessName() else {
            (getSystemService(ACTIVITY_SERVICE) as ActivityManager).runningAppProcesses
                ?.firstOrNull { it.pid == Process.myPid() }?.processName
        }
        if (process != packageName) return
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        val preferences = getSharedPreferences("qualification", MODE_PRIVATE)
        val key = preferences.getString("key", null) ?: Base64.encodeToString(
            ByteArray(32).also { SecureRandom().nextBytes(it) }, Base64.NO_WRAP,
        ).also { check(preferences.edit().putString("key", it).commit()) }
        val request = JSONObject().put("profile_dir", File(filesDir, "profile").absolutePath)
            .put("vault_key", key).put("display_name", "Independent consumer host").put("platform", "android")
        val reply = Python.getInstance().getModule("mesh_chat.mobile_bridge")
            .callAttr("initialize", request.toString()).toString()
        check(JSONObject(reply).getBoolean("ok")) { "Qualification host did not initialize" }
        // A real owner-created target makes the cross-UID denial test meaningful.
        val workspace = JSONObject().put("command", "create_workspace").put("payload", JSONObject()
            .put("operation_id", "6bfa1240-222f-4905-a3dd-868193a200c3")
            .put("name", "Consumer qualification"))
        val created = Python.getInstance().getModule("mesh_chat.mobile_bridge")
            .callAttr("command", workspace.toString()).toString()
        check(JSONObject(created).getBoolean("ok")) { "Qualification workspace did not initialize" }
        // A host-owned approved contact makes the public enqueue/read path testable
        // without a second device or a real transport. Keep seeding best-effort so a
        // fixture problem cannot take down the host service for the other cases.
        runCatching {
            val bridge = Python.getInstance().getModule("mesh_chat.mobile_bridge")
            val service = bridge.callAttr("__getattribute__", "_service")
            val store = service.callAttr("__getattribute__", "store")
            val now = System.currentTimeMillis() / 1000.0
            val contact = JSONObject()
                .put("id", "fixture-peer-0001")
                .put("display_name", "Fixture peer")
                .put("destination_hash", "ab".repeat(16))
                .put("identity_hash", "cd".repeat(16))
                .put("public_identity", "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
                .put("trust", "approved")
                .put("created_at", now)
                .put("updated_at", now)
                .put("connection_hints", org.json.JSONArray())
            val decoded = Python.getInstance().getModule("json")
                .callAttr("loads", contact.toString())
            store.callAttr("put", "contact", "fixture-peer-0001", decoded)
        }
    }
}
