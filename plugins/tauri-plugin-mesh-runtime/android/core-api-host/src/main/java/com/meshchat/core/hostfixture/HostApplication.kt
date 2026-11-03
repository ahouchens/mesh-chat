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
    }
}
