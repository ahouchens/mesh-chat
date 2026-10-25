package com.meshchat.runtime

import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Real Chromium SDP, JNI, CPython command/callback locks and SCTP traffic.
 * This is an emulator interoperability proof, not a cellular/Doze proof.
 */
@RunWith(AndroidJUnit4::class)
class NativeWebRtcInteropTest {
    class BrowserResults {
        val messages = LinkedBlockingQueue<Pair<String, String>>()
        @JavascriptInterface fun result(kind: String, value: String) { messages.offer(kind to value) }
        fun await(kind: String, value: String? = null): String {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(40)
            while (System.nanoTime() < deadline) {
                val message = messages.poll(1, TimeUnit.SECONDS) ?: continue
                if (message.first == "error") fail(message.second)
                if (message.first == kind && (value == null || value == message.second)) return message.second
            }
            throw AssertionError("Chromium did not report $kind")
        }
    }

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    private fun command(name: String, payload: JSONObject = JSONObject()): JSONObject {
        val raw = Python.getInstance().getModule("mesh_chat.mobile_bridge").callAttr("command",
            JSONObject().put("command", name).put("payload", payload).toString()).toString()
        val response = JSONObject(raw)
        assertTrue("$name failed: $raw", response.optBoolean("ok"))
        return response.optJSONObject("result") ?: JSONObject()
    }

    private fun awaitStats(session: String, predicate: (JSONObject) -> Boolean): JSONObject {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(40)
        var last = JSONObject()
        while (System.nanoTime() < deadline) {
            last = command("native_webrtc_stats", JSONObject().put("session_id", session))
            if (predicate(last)) return last
            Thread.sleep(100)
        }
        throw AssertionError("Native transport did not become ready: $last")
    }

    @Test(timeout = 180_000) fun chromiumOfferCanBeAcceptedThroughTheRealPythonBridge() = exchange(nativeOffers = false)
    @Test(timeout = 180_000) fun nativeOfferCanConnectToChromiumWithReconnectControl() = exchange(nativeOffers = true)

    @Test(timeout = 90_000) fun backgroundRuntimeCanInitializeNativeWebRtc() {
        BackgroundRuntime.configure(context)
        try {
            assertTrue(JSONObject(BackgroundRuntime.initialize()).optBoolean("ok"))
            val status = JSONObject(BackgroundRuntime.status())
            assertTrue(status.optBoolean("runtime_initialized"))
            assertTrue(status.optBoolean("native_webrtc_ready"))
            command("snapshot")
        } finally {
            NativeWebRtcHost.closeAll()
            BackgroundRuntime.onRuntimeShutdown()
            if (Python.isStarted()) {
                Python.getInstance().getModule("mesh_chat.mobile_bridge").callAttr("shutdown")
            }
        }
    }

    private fun assertCloseDoesNotBlockTheMainThread(channels: JSONArray) {
        val id = "cancel-${UUID.randomUUID()}"
        val worker = Executors.newSingleThreadExecutor()
        val ice = JSONObject().put("iceTransportPolicy", "all").put("iceServers", JSONArray().put(
            JSONObject().put("urls", JSONArray().put("stun:192.0.2.1:3478"))))
        val pending = worker.submit<String> { NativeWebRtcHost.createOffer(id, ice.toString(), channels.toString()) }
        try {
            // Observe registration without waiting for stats(), which shares
            // the SDP lifetime lock. No production-only testing hook is used.
            val field = NativeWebRtcHost::class.java.getDeclaredField("sessions").apply { isAccessible = true }
            val sessions = field.get(NativeWebRtcHost) as Map<*, *>
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
            while (!sessions.containsKey(id) && System.nanoTime() < deadline) Thread.sleep(10)
            assertTrue("Native cancellation test did not create a session", sessions.containsKey(id))
            val started = System.nanoTime()
            instrumentation.runOnMainSync { NativeWebRtcHost.close(id) }
            assertTrue("Closing during ICE gathering blocked the Android main thread",
                System.nanoTime() - started < TimeUnit.SECONDS.toNanos(1))
            pending.get(35, TimeUnit.SECONDS)
            assertFalse(JSONObject(NativeWebRtcHost.stats(id)).optBoolean("ok"))
        } finally {
            NativeWebRtcHost.close(id)
            worker.shutdownNow()
        }
    }

    private fun exchange(nativeOffers: Boolean) {
        val id = "interop-${UUID.randomUUID()}"
        val control = if (nativeOffers) "meshchat-reconnect" else "mesh-onboarding"
        val results = BrowserResults()
        lateinit var browser: WebView
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        NativeWebRtcHost.attachContext(context)
        val module = Python.getInstance().getModule("mesh_chat.mobile_bridge")
        val initialized = module.callAttr("initialize", JSONObject()
            .put("profile_dir", context.filesDir.resolve("webrtc-ci/$id").absolutePath)
            .put("vault_key", Base64.encodeToString(ByteArray(32) { (it + 1).toByte() }, Base64.NO_WRAP))
            .put("display_name", "WebRTC CI")
            .put("platform", "android").toString()).toString()
        assertTrue(initialized, JSONObject(initialized).optBoolean("ok"))
        try {
            instrumentation.runOnMainSync {
                browser = WebView(context)
                browser.settings.javaScriptEnabled = true
                browser.addJavascriptInterface(results, "TestResults")
                browser.loadDataWithBaseURL("https://meshchat.invalid/", """
                    <script>
                    const channels = {};
                    const report = (k,v) => TestResults.result(k, String(v));
                    const install = c => {
                      channels[c.label] = c; c.binaryType = 'arraybuffer';
                      c.onmessage = e => report(c.label, typeof e.data === 'string' ? e.data : Array.from(new Uint8Array(e.data)).join(','));
                    };
                    const pc = new RTCPeerConnection({iceServers: []});
                    pc.ondatachannel = e => install(e.channel);
                    const gather = () => new Promise(resolve => {
                      if (pc.iceGatheringState === 'complete') return resolve();
                      pc.addEventListener('icegatheringstatechange', () => {
                        if (pc.iceGatheringState === 'complete') resolve();
                      });
                    });
                    window.offer = async () => {
                      install(pc.createDataChannel('mesh-reticulum'));
                      install(pc.createDataChannel('$control'));
                      await pc.setLocalDescription(await pc.createOffer()); await gather();
                      report('sdp', pc.localDescription.sdp);
                    };
                    window.answer = async sdp => {
                      await pc.setRemoteDescription({type:'offer',sdp});
                      await pc.setLocalDescription(await pc.createAnswer()); await gather();
                      report('sdp', pc.localDescription.sdp);
                    };
                    window.finish = sdp => pc.setRemoteDescription({type:'answer',sdp}).catch(e => report('error',e));
                    window.probe = async () => {
                      const deadline = Date.now() + 20000;
                      while (channels['mesh-reticulum']?.readyState !== 'open' || channels['$control']?.readyState !== 'open') {
                        if (Date.now() > deadline) throw new Error('Chromium channels did not open');
                        await new Promise(resolve => setTimeout(resolve, 50));
                      }
                      channels['mesh-reticulum'].send(new Uint8Array([9,8,7]));
                      channels['$control'].send('probe'); report('sent','yes');
                    };
                    report('ready','yes');
                    </script>
                """.trimIndent(), "text/html", "UTF-8", null)
            }
            results.await("ready")
            fun js(script: String) = instrumentation.runOnMainSync {
                browser.evaluateJavascript("Promise.resolve().then(() => {$script}).catch(e => TestResults.result('error',String(e)))", null)
            }
            val channels = JSONArray().put(JSONObject().put("label", "mesh-reticulum").put("binary", true).put("ordered", true))
                .put(JSONObject().put("label", control).put("binary", false).put("ordered", true))
            val payload = JSONObject().put("session_id", id).put("ice", JSONObject().put("iceServers", JSONArray()).put("iceTransportPolicy", "all"))
                .put("channels", channels)
            if (nativeOffers) {
                val native = command("native_webrtc_offer", payload)
                assertTrue(native.getString("fingerprint").startsWith("sha-256 "))
                js("return answer(${JSONObject.quote(native.getString("sdp"))})")
                command("native_webrtc_apply_answer", JSONObject().put("session_id", id).put("answer_sdp", results.await("sdp")))
            } else {
                js("return offer()")
                val native = command("native_webrtc_accept", payload.put("offer_sdp", results.await("sdp")))
                assertTrue(native.getString("fingerprint").startsWith("sha-256 "))
                js("return finish(${JSONObject.quote(native.getString("sdp"))})")
            }
            awaitStats(id) { it.optBoolean("attached") && it.optString("ice_connection_state") in setOf("connected", "completed") }
            js("return probe()")
            results.await("sent")
            awaitStats(id) { it.optLong("received_packets") >= 1 && it.optLong("received_controls") >= 1 }
            assertTrue(NativeWebRtcHost.send(id, byteArrayOf(4, 5, 6)))
            assertEquals("4,5,6", results.await("mesh-reticulum"))
            assertTrue(NativeWebRtcHost.sendControl(id, control, "probe-reply"))
            assertEquals("probe-reply", results.await(control, "probe-reply"))
            command("native_webrtc_close", JSONObject().put("session_id", id))
            assertFalse(JSONObject(NativeWebRtcHost.stats(id)).optBoolean("ok"))
            Thread.sleep(300) // Let late close/state callbacks drain before leaving the test.
            command("snapshot")
            if (nativeOffers) assertCloseDoesNotBlockTheMainThread(channels)
            js("pc.close()")
        } finally {
            NativeWebRtcHost.closeAll()
            module.callAttr("shutdown")
            instrumentation.runOnMainSync {
                try { browser.destroy() } catch (_: UninitializedPropertyAccessException) { }
            }
        }
    }
}
