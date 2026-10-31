package com.meshchat.runtime

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.IBinder
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MeshCoreApiServiceTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext

    private fun withService(action: (IMeshCoreApi) -> Unit) {
        val latch = CountDownLatch(1)
        var connected: IMeshCoreApi? = null
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
                connected = IMeshCoreApi.Stub.asInterface(service)
                latch.countDown()
            }

            override fun onServiceDisconnected(name: ComponentName?) {
                connected = null
            }
        }
        val intent = Intent(context, MeshCoreApiService::class.java)
        check(context.bindService(intent, connection, Context.BIND_AUTO_CREATE)) { "bind failed" }
        try {
            check(latch.await(15, TimeUnit.SECONDS)) { "service did not bind" }
            action(checkNotNull(connected))
        } finally {
            context.unbindService(connection)
        }
    }

    private fun exchange(api: IMeshCoreApi, frame: ByteArray): JSONObject =
        JSONObject(String(api.exchange(frame), Charsets.UTF_8).trim())

    private fun errorCode(reply: JSONObject): String = reply.getJSONObject("error").getString("code")

    @Test
    fun serviceIsExportedBehindTheSignaturePermission() {
        val info = context.packageManager.getServiceInfo(
            ComponentName(context, MeshCoreApiService::class.java), 0,
        )
        assertEquals(MeshCoreApiService.PERMISSION, info.permission)
        assertTrue(info.exported)
        assertEquals(
            PackageManager.PERMISSION_GRANTED,
            context.packageManager.checkPermission(
                MeshCoreApiService.PERMISSION, context.packageName,
            ),
        )
    }

    @Test
    fun emptyFrameIsRejectedBeforeDispatch() {
        withService { api ->
            assertEquals("invalid_request", errorCode(exchange(api, ByteArray(0))))
        }
    }

    @Test
    fun oversizedFrameIsRejectedBeforeDispatch() {
        withService { api ->
            val oversized = ByteArray(MeshCoreApiService.MAX_FRAME_BYTES + 1)
            assertEquals("invalid_request", errorCode(exchange(api, oversized)))
        }
    }

    @Test
    fun uninitializedBridgeFailsClosedWithATypedFrame() {
        withService { api ->
            val frame = (
                "{\"api_version\":1,\"request_id\":\"android:1\"," +
                    "\"operation\":\"runtime.capabilities\",\"params\":{}}\n"
                ).toByteArray(Charsets.UTF_8)
            val reply = exchange(api, frame)
            assertFalse(reply.getBoolean("ok"))
            assertEquals("unavailable", errorCode(reply))
        }
    }
}
