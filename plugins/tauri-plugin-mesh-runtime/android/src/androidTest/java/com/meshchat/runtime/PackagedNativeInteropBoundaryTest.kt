package com.meshchat.runtime

import android.os.Bundle
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.security.MessageDigest

/** Explicit CI instrumentation only. No exported product service or JSON grant. */
@RunWith(AndroidJUnit4::class)
class PackagedNativeInteropBoundaryTest {
    @Test(timeout = 3_600_000)
    fun packagedNativePeerController() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val nonce = InstrumentationRegistry.getArguments().getString("mesh_interop_nonce") ?: error("Missing controller admission")
        check(nonce.matches(Regex("[a-f0-9]{64}")))
        BootstrapClient.configure(context)
        NativeWebRtcBridge.attach(context)
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        val python = Python.getInstance()
        val qualification = python.getModule("mesh_chat.core_api.qualification_host")
        val mobile = python.getModule("mesh_chat.mobile_bridge")
        var directory: File? = null
        var initialized = false
        var finished = false
        var authenticated = false
        val parent = context.filesDir.resolve("native-interop").canonicalFile
        check(parent.mkdirs() || parent.isDirectory)
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 90_000
            instrumentation.sendStatus(0, Bundle().apply { putString("mesh_interop_port", server.localPort.toString()) })
            try {
                server.accept().use { socket ->
                    socket.soTimeout = 120_000
                    val input = DataInputStream(socket.getInputStream())
                    val output = DataOutputStream(socket.getOutputStream())
                    while (!finished) {
                        val size = input.readInt()
                        check(size in 2..4 * 1024 * 1024)
                        val bytes = ByteArray(size)
                        input.readFully(bytes)
                        val frame = JSONObject(String(bytes, Charsets.UTF_8))
                        check(frame.keys().asSequence().toSet() == setOf("id", "action", "payload"))
                        val id = frame.getString("id")
                        check(id.matches(Regex("qualification:[0-9]{1,8}")))
                        val action = frame.getString("action")
                        val payload = frame.getJSONObject("payload")
                        var reply: JSONObject
                        try {
                            if (!authenticated) {
                                check(action == "authenticate" && payload.keys().asSequence().toSet() == setOf("nonce"))
                                check(MessageDigest.isEqual(nonce.toByteArray(), payload.getString("nonce").toByteArray()))
                                authenticated = true
                                reply = JSONObject().put("ok", true).put("result", JSONObject().put("authenticated", true))
                            } else when (action) {
                                "initialize" -> {
                                    check(!initialized && payload.keys().asSequence().toSet() == setOf("directory_id", "vault_key"))
                                    val leaf = payload.getString("directory_id")
                                    check(leaf.matches(Regex("[a-f0-9]{32}")))
                                    check(Base64.decode(payload.getString("vault_key"), Base64.NO_WRAP).size == 32)
                                    directory = parent.resolve("mesh-qualification-$leaf").canonicalFile
                                    check(directory!!.parentFile == parent)
                                    val request = JSONObject().put("profile_dir", directory!!.absolutePath)
                                        .put("vault_key", payload.getString("vault_key")).put("display_name", "Mesh qualification")
                                        .put("platform", "android")
                                    reply = JSONObject(qualification.callAttr("android_initialize", request.toString()).toString())
                                    initialized = reply.optBoolean("ok")
                                }
                                "core" -> {
                                    check(initialized && payload.keys().asSequence().toSet() == setOf("operation", "params", "idempotency_key"))
                                    val request = JSONObject().put("action", "request").put("payload", JSONObject()
                                        .put("operation", payload.getString("operation")).put("params", payload.getJSONObject("params"))
                                        .put("idempotencyKey", payload.get("idempotency_key")))
                                    reply = JSONObject(CoreApiBridge.typedCommand(context, request.toString()))
                                }
                                "inspect" -> {
                                    check(initialized && payload.keys().asSequence().toSet() == setOf("command", "payload"))
                                    reply = JSONObject(qualification.callAttr("android_control", payload.toString()).toString())
                                }
                                "finish" -> {
                                    check(initialized && payload.keys().asSequence().toSet() == setOf("delete_profile"))
                                    val closed = JSONObject(mobile.callAttr("shutdown").toString())
                                    check(closed.getBoolean("ok"))
                                    initialized = false
                                    NativeWebRtcBridge.closeAll()
                                    val host = Class.forName("com.meshchat.runtime.NativeWebRtcHost")
                                    val reservationsField = host.getDeclaredField("reservations").apply { isAccessible = true }
                                    val reservations = reservationsField.get(null)
                                    val ids = reservations.javaClass.getMethod("ids")
                                    val deadline = System.nanoTime() + 15_000_000_000L
                                    var retired = false
                                    while (System.nanoTime() < deadline) {
                                        // Inspect actual retained ownership; shutdown may defer close.
                                        mobile.callAttr("shutdown")
                                        val storeRetired = python.builtins.callAttr("eval",
                                            "_service is None and _retiring_service is None and _retiring_channel is None",
                                            mobile.get("__dict__")).toString() == "True"
                                        val resourcesRetired = (ids.invoke(reservations) as List<*>).isEmpty()
                                        if (storeRetired && resourcesRetired) { retired = true; break }
                                        Thread.sleep(25)
                                    }
                                    check(retired)
                                    if (payload.getBoolean("delete_profile")) {
                                        check(directory!!.parentFile == parent)
                                        check(directory!!.deleteRecursively())
                                    }
                                    finished = true
                                    reply = JSONObject().put("ok", true).put("result", JSONObject().put("closed", true)
                                        .put("resources_retired", true).put("store_retired", true))
                                }
                                else -> error("Unsupported controller action")
                            }
                        } catch (_: Throwable) {
                            // Raw exceptions may contain signed signaling or caller payloads.
                            reply = JSONObject().put("ok", false).put("error", JSONObject().put("code", "qualification_host_error"))
                        }
                        reply.put("id", id)
                        val encoded = reply.toString().toByteArray(Charsets.UTF_8)
                        check(encoded.size in 2..4 * 1024 * 1024)
                        output.writeInt(encoded.size)
                        output.write(encoded)
                        output.flush()
                        if (!authenticated) error("Controller authentication failed")
                    }
                }
            } finally {
                if (initialized) mobile.callAttr("shutdown")
                NativeWebRtcBridge.closeAll()
            }
        }
        check(finished)
    }
}
