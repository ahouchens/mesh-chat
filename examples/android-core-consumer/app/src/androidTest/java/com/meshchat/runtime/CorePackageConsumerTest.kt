package com.meshchat.runtime

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import android.os.Process
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.meshchat.runtime.core.CoreClient
import com.meshchat.runtime.core.CoreException
import com.meshchat.runtime.core.CoreExchangeTransport
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Imports only Android and the staged public client AAR, never host classes. */
@RunWith(AndroidJUnit4::class)
class CorePackageConsumerTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val host = "com.meshchat.core.hostfixture"

    private fun withClient(action: (CoreClient) -> Unit) {
        assertNotEquals(Process.myUid(), context.packageManager.getApplicationInfo(host, 0).uid)
        val connected = CountDownLatch(1)
        var remote: IMeshCoreApi? = null
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                remote = IMeshCoreApi.Stub.asInterface(binder)
                connected.countDown()
            }
            override fun onServiceDisconnected(name: ComponentName) { remote = null }
        }
        val intent = Intent().setComponent(ComponentName(host, "com.meshchat.runtime.MeshCoreApiService"))
        assertTrue(context.bindService(intent, connection, Context.BIND_AUTO_CREATE))
        try {
            assertTrue(connected.await(60, TimeUnit.SECONDS))
            val client = CoreClient.open(CoreExchangeTransport { checkNotNull(remote).exchange(it) })
            try { action(client) } finally { client.close() }
        } finally { context.unbindService(connection) }
    }

    private fun profile(client: CoreClient) = client.capabilities.getJSONArray("profiles").getString(0)

    @Test fun consumerQueriesProductionFacadeAcrossUid() {
        withClient { client ->
            assertEquals(1, client.capabilities.getInt("api_major"))
            assertTrue(client.profileQuery(profile(client)).length() > 0)
        }
    }

    @Test fun externalCallerCannotAcquireOwnerScope() {
        withClient { client ->
            val profile = profile(client)
            val workspace = client.workspaceList(profile).getJSONArray("workspaces")
                .getJSONObject(0).getString("workspace")
            val error = runCatching {
                client.workspaceChannelCreate(profile, workspace, "Forbidden", "external-owner-check")
            }.exceptionOrNull()
            assertTrue(error is CoreException)
            assertEquals("forbidden", (error as CoreException).code)
        }
    }

    @Test fun detachingConsumerCanReattachToItsProfile() {
        var previous: String? = null
        withClient { previous = it.profileQuery(profile(it)).toString() }
        withClient { assertEquals(previous, it.profileQuery(profile(it)).toString()) }
    }

    @Test fun privateControlIsRejectedThroughThePublicPackage() {
        withClient { client ->
            val error = runCatching { client.request("native_webrtc_offer", JSONObject()) }.exceptionOrNull()
            assertTrue(error is CoreException)
            assertEquals("unsupported_operation", (error as CoreException).code)
        }
    }
}
