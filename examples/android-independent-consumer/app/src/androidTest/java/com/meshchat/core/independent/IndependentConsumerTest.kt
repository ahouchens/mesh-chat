package com.meshchat.runtime

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import android.os.Process
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.meshchat.core.independent.ConsumerApplication
import com.meshchat.runtime.core.CoreClient
import com.meshchat.runtime.core.CoreException
import com.meshchat.runtime.core.CoreExchangeTransport
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class IndependentConsumerTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val application get() = context.applicationContext as ConsumerApplication
    private fun key() = UUID.randomUUID().toString()

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

    private fun expectCode(code: String, action: () -> Unit) {
        val error = runCatching(action).exceptionOrNull()
        assertTrue(error is CoreException)
        assertEquals(code, (error as CoreException).code)
    }

    @Test fun freshLifecycleCreatesOnceAndRetires() {
        assertEquals(MeshCoreRuntime.State.UNLOCKED, checkNotNull(application.startup).get(90, TimeUnit.SECONDS))
        var profile = ""
        var destination = ""
        withClient { client ->
            assertFalse(client.capabilities.getJSONArray("operations").toString().contains("native.command"))
            val empty = client.applicationSnapshot()
            assertTrue(empty.isNull("profile"))
            assertEquals(0, empty.getJSONArray("contacts").length())
            assertEquals(0, empty.getJSONArray("messages").length())
            val originalKey = key()
            val params = JSONObject().put("display_name", "Independent Android")
            val created = client.request("profile.create", params, originalKey)
            assertEquals(created.toString(), client.request("profile.create", params, originalKey).toString())
            expectCode("idempotency_conflict") {
                client.request("profile.create", JSONObject().put("display_name", "Changed"), originalKey)
            }
            profile = client.request("runtime.capabilities").getJSONArray("profiles").getString(0)
            destination = client.profileQuery(profile).getString("destination")
            expectCode("unsupported_operation") { client.nativeCommand("native.test") }
        }
        // Closing/unbinding the SDK must not retire the application's runtime.
        withClient { client ->
            assertEquals(destination, client.profileQuery(profile).getString("destination"))
            client.lockProfile(profile, key())
            expectCode("locked") { client.profileQuery(profile) }
        }
        assertTrue(context.getSharedPreferences("consumer-observations", Context.MODE_PRIVATE).edit()
            .putString("profile", profile).putString("destination", destination)
            .putInt("seed-process", Process.myPid()).commit())
        MeshCoreRuntime.shutdown().get(60, TimeUnit.SECONDS)
        assertEquals(MeshCoreRuntime.State.LOCKED, MeshCoreRuntime.start(context).get(90, TimeUnit.SECONDS))
        withClient { expectCode("locked") { it.profileQuery(profile) } }
        MeshCoreRuntime.shutdown().get(60, TimeUnit.SECONDS)
    }

    @Test fun coldStartRequiresNativeCredential() {
        // The runner force-stops the entire package between these two cases.
        assertEquals(MeshCoreRuntime.State.LOCKED, checkNotNull(application.startup).get(90, TimeUnit.SECONDS))
        val observations = context.getSharedPreferences("consumer-observations", Context.MODE_PRIVATE)
        assertNotEquals(observations.getInt("seed-process", -1), Process.myPid())
        val profile = checkNotNull(observations.getString("profile", null))
        withClient { client ->
            assertEquals(profile, client.capabilities.getJSONArray("profiles").getString(0))
            expectCode("locked") { client.profileQuery(profile) }
            expectCode("forbidden") { client.unlockProfile(profile, "unknown-credential-handle", key()) }
            expectCode("locked") { client.profileQuery(profile) }
            assertFalse(client.capabilities.getJSONArray("operations").toString().contains("native.command"))
        }
        MeshCoreRuntime.shutdown().get(60, TimeUnit.SECONDS)
    }
}
