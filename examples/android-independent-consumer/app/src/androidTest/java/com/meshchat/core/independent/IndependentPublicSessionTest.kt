package com.meshchat.runtime

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.IBinder
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.meshchat.core.independent.ConsumerApplication
import com.meshchat.runtime.core.CoreClient
import com.meshchat.runtime.core.CoreException
import com.meshchat.runtime.core.CoreExchangeTransport
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Test-only loopback driver. Every product action uses the installed public SDK and own Binder service. */
@RunWith(AndroidJUnit4::class)
class IndependentPublicSessionTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private val operations = setOf("runtime.capabilities", "application.snapshot", "profile.create", "profile.query",
        "settings.query", "settings.update", "call.settings_query", "call.settings_update",
        "peer.pairing_begin", "peer.pairing_query", "peer.pairing_cancel", "contact.invitation", "peer.approve",
        "connection.snapshot", "connection.start", "message.enqueue", "message.query", "message.received")

    private fun keys(value: JSONObject) = value.keys().asSequence().toSet()

    private fun frame(input: DataInputStream): JSONObject {
        val size = input.readInt()
        check(size in 2..65536) { "public_session_frame_budget" }
        val bytes = ByteArray(size)
        input.readFully(bytes)
        val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
        return JSONObject(text)
    }

    private fun reply(output: DataOutputStream, value: JSONObject) {
        val bytes = value.toString().toByteArray(Charsets.UTF_8)
        check(bytes.size in 2..65536) { "public_session_reply_budget" }
        output.writeInt(bytes.size)
        output.write(bytes)
        output.flush()
    }

    private fun identifier(value: JSONObject): String {
        val id = value.get("id")
        check(id is String && id.matches(Regex("[A-Za-z0-9:_-]{1,64}"))) { "public_session_id" }
        return id
    }

    private fun withClient(action: (CoreClient) -> Unit) {
        val connected = CountDownLatch(1)
        var remote: IMeshCoreApi? = null
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                remote = IMeshCoreApi.Stub.asInterface(binder)
                connected.countDown()
            }
            override fun onServiceDisconnected(name: ComponentName) { remote = null }
        }
        assertTrue(context.bindService(Intent().setComponent(ComponentName(context.packageName,
            "com.meshchat.runtime.MeshCoreApiService")), connection, Context.BIND_AUTO_CREATE))
        try {
            assertTrue(connected.await(60, TimeUnit.SECONDS))
            val client = CoreClient.open(CoreExchangeTransport { checkNotNull(remote).exchange(it) })
            try { action(client) } finally { client.close() }
        } finally { context.unbindService(connection) }
    }

    @Test(timeout = 900_000)
    fun publicSessionAcrossMultiplePhases() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val nonce = InstrumentationRegistry.getArguments().getString("mesh_public_nonce")
            ?: error("Missing public session admission")
        check(nonce.matches(Regex("[a-f0-9]{64}")))
        assertTrue(MeshCoreRuntime.isMainProcess(context))
        val application = context.applicationContext as ConsumerApplication
        assertEquals(MeshCoreRuntime.State.UNLOCKED, checkNotNull(application.startup).get(90, TimeUnit.SECONDS))
        var completed = false
        try {
            withClient { client ->
                assertFalse(client.capabilities.getJSONArray("operations").toString().contains("native.command"))
                ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
                    server.soTimeout = 90_000
                    instrumentation.sendStatus(0, Bundle().apply {
                        putString("mesh_public_port", server.localPort.toString())
                    })
                    server.accept().use { socket ->
                        socket.soTimeout = 180_000
                        val input = DataInputStream(socket.getInputStream())
                        val output = DataOutputStream(socket.getOutputStream())
                        val auth = frame(input)
                        check(keys(auth) == setOf("id", "action", "nonce") && auth.getString("action") == "authenticate")
                        check(MessageDigest.isEqual(nonce.toByteArray(), auth.getString("nonce").toByteArray()))
                        reply(output, JSONObject().put("id", identifier(auth)).put("ok", true)
                            .put("result", JSONObject().put("authenticated", true)))
                        var requests = 0
                        var created = false
                        while (!completed) {
                            val command = frame(input)
                            val id = identifier(command)
                            val step = command.get("step")
                            check(step is Int && step == requests + 1 && requests < 128)
                            when (command.getString("action")) {
                                "request" -> {
                                    check(keys(command) == setOf("id", "action", "step", "operation", "params") ||
                                        keys(command) == setOf("id", "action", "step", "operation", "params", "idempotency_key"))
                                    val operation = command.getString("operation")
                                    check(operation in operations)
                                    val params = command.getJSONObject("params")
                                    val key = command.opt("idempotency_key")
                                    check(key == null || key is String && key.matches(Regex("[A-Za-z0-9._:-]{16,128}")))
                                    requests++
                                    val answer = try {
                                        val result = if (key == null) client.request(operation, params)
                                            else client.request(operation, params, key as String)
                                        if (operation == "profile.create") created = true
                                        JSONObject().put("id", id).put("ok", true).put("result", result)
                                    } catch (error: CoreException) {
                                        check(error.code.matches(Regex("[a-z_]{1,64}")))
                                        JSONObject().put("id", id).put("ok", false)
                                            .put("error", JSONObject().put("code", error.code))
                                    }
                                    reply(output, answer)
                                }
                                "finish" -> {
                                    check(keys(command) == setOf("id", "action", "step") && created && requests >= 4)
                                    completed = true
                                    reply(output, JSONObject().put("id", id).put("ok", true)
                                        .put("result", JSONObject().put("completed", true).put("requests", requests)))
                                }
                                else -> error("Unknown public session action")
                            }
                        }
                    }
                }
            }
        } finally {
            MeshCoreRuntime.shutdown().get(60, TimeUnit.SECONDS)
        }
        assertTrue(completed)
    }
}
