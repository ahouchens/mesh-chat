package com.meshchat.runtime

import android.util.Base64
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.os.Build
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
    @Test(timeout = 180_000) fun chromiumOfferSurvivesEarlyIceFailureDuringManualAnswerExchange() =
        exchange(nativeOffers = false, earlyIceFailure = true)
    @Test(timeout = 180_000) fun nativeOfferCanConnectToChromiumWithReconnectControl() = exchange(nativeOffers = true)
    @Test(timeout = 180_000) fun repeatedChromiumMediaCallsPreserveNativeMessaging() =
        exchange(nativeOffers = false, repeatedMedia = true)

    @Test(timeout = 30_000) fun backgroundDefaultResumesAfterUnlockAndPreservesAnExplicitOffChoice() {
        val prefs = context.getSharedPreferences("mesh-chat-vault", Context.MODE_PRIVATE)
        val keys = listOf("background-availability-enabled", "background-availability-default-v2", "background-availability-preference-v2")
        val saved = keys.associateWith { if (prefs.contains(it)) prefs.getBoolean(it, false) else null }
        try {
            prefs.edit().apply { keys.forEach { remove(it) } }.commit()
            BackgroundRuntime.applyDefault(context)
            assertTrue(BackgroundRuntime.isEnabled(context))
            BackgroundRuntime.stop(context, preservePreference = true)
            assertFalse(BackgroundRuntime.isEnabled(context))
            BackgroundRuntime.applyDefault(context)
            assertTrue(BackgroundRuntime.isEnabled(context))
            BackgroundRuntime.setPreference(context, false)
            BackgroundRuntime.applyDefault(context)
            assertFalse(BackgroundRuntime.isEnabled(context))
        } finally {
            prefs.edit().apply { saved.forEach { (key, value) -> if (value == null) remove(key) else putBoolean(key, value) } }.commit()
        }
    }

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

    @Test(timeout = 30_000) fun queuedAvailabilityStartHonorsStopWithoutCrashingOrOpeningTheRuntime() {
        BackgroundRuntime.configure(context)
        BackgroundRuntime.setPreference(context, false)
        val launch = Intent().setClassName(context, "com.meshchat.runtime.smoke.BackgroundTestActivity")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val activity = instrumentation.startActivitySync(launch)
        try {
            instrumentation.runOnMainSync {
                val service = Intent(context, MeshAvailabilityService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(service)
                else context.startService(service)
            }
            // Observe Android's foreground-promotion deadline, including a
            // delayed process exception after an apparently successful Stop.
            Thread.sleep(7_000)
            assertFalse(MeshAvailabilityService.isRunning())
            assertFalse(BackgroundRuntime.statusJson().optBoolean("runtime_initialized"))
            assertFalse(BackgroundRuntime.isEnabled(context))
        } finally {
            BackgroundRuntime.stop(context)
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    @Test(timeout = 180_000) fun optedInServiceRestoresAndKeepsNativeTrafficWhileActivityIsStopped() {
        BackgroundRuntime.configure(context)
        assertTrue(JSONObject(BackgroundRuntime.initialize()).optBoolean("ok"))
        // Simulate an update/process restart: persisted opt-in, no Service.
        BackgroundRuntime.setPreference(context, true)
        command("set_background_availability", JSONObject().put("enabled", true))
        assertFalse(MeshAvailabilityService.isRunning())
        val launch = Intent().setClassName(context, "com.meshchat.runtime.smoke.BackgroundTestActivity")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        var activity = instrumentation.startActivitySync(launch)
        fun awaitState(message: String, condition: () -> Boolean) {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20)
            while (!condition() && System.nanoTime() < deadline) Thread.sleep(100)
            assertTrue(message, condition())
        }
        fun nativeStats(id: String): JSONObject = JSONObject(NativeWebRtcHost.stats(id)).getJSONObject("result")
        fun assertForegroundService() {
            val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            @Suppress("DEPRECATION")
            assertTrue("Android did not promote the availability Service", manager.getRunningServices(20).any {
                it.service.className == MeshAvailabilityService::class.java.name && it.foreground
            })
            assertTrue(BackgroundRuntime.statusJson().optBoolean("notification_visible"))
            assertTrue(BackgroundRuntime.statusJson().optBoolean("multicast_lock_held"))
        }
        try {
            awaitState("Saved opt-in did not restore the Service") {
                MeshAvailabilityService.isRunning() && BackgroundRuntime.statusJson().optBoolean("notification_visible")
            }
            assertForegroundService()
            val channels = JSONArray().put(JSONObject().put("label", "mesh-reticulum").put("binary", true).put("ordered", true))
            val ice = JSONObject().put("iceServers", JSONArray()).put("iceTransportPolicy", "all").toString()
            val offer = JSONObject(NativeWebRtcHost.createOffer("background-a", ice, channels.toString()))
            assertTrue(offer.toString(), offer.getBoolean("ok"))
            val answer = JSONObject(NativeWebRtcHost.acceptOffer("background-b", offer.getString("sdp"), ice, channels.toString()))
            assertTrue(answer.toString(), answer.getBoolean("ok"))
            assertTrue(JSONObject(NativeWebRtcHost.applyAnswer("background-a", answer.getString("sdp"))).getBoolean("ok"))
            awaitState("Native channels did not open") {
                nativeStats("background-a").optString("data_channel_state") == "open" &&
                    nativeStats("background-b").optString("data_channel_state") == "open"
            }
            instrumentation.runOnMainSync { assertTrue(activity.moveTaskToBack(true)) }
            awaitState("The Activity did not leave the foreground") { !BackgroundRuntime.statusJson().optBoolean("ui_foreground") }
            repeat(12) {
                assertForegroundService()
                assertTrue(NativeWebRtcHost.send("background-a", byteArrayOf(1, 2, 3)))
                assertTrue(NativeWebRtcHost.send("background-b", byteArrayOf(4, 5, 6)))
                Thread.sleep(1000)
            }
            assertTrue(nativeStats("background-a").getLong("received_packets") >= 12)
            assertTrue(nativeStats("background-b").getLong("received_packets") >= 12)
            // A stopped Service is restored on the next foreground launch,
            // without replacing the established native transport.
            context.stopService(Intent(context, MeshAvailabilityService::class.java))
            awaitState("Service did not stop") { !MeshAvailabilityService.isRunning() }
            assertTrue(BackgroundRuntime.isEnabled(context))
            instrumentation.runOnMainSync { activity.finish() }
            activity = instrumentation.startActivitySync(launch)
            awaitState("Returning to the app did not restore its Service and network lock") {
                MeshAvailabilityService.isRunning() && BackgroundRuntime.statusJson().optBoolean("multicast_lock_held")
            }
            assertEquals("open", nativeStats("background-a").getString("data_channel_state"))
            assertTrue(BackgroundRuntime.statusJson().getInt("restorations") >= 2)
            // Explicit opt-out must win over a later foreground resume.
            BackgroundRuntime.stop(context)
            command("set_background_availability", JSONObject().put("enabled", false))
            awaitState("Explicit stop did not stop the Service") { !MeshAvailabilityService.isRunning() }
            instrumentation.runOnMainSync { BackgroundRuntime.restoreIfEnabled(context) }
            assertFalse(BackgroundRuntime.isEnabled(context))
            assertFalse(MeshAvailabilityService.isRunning())
        } finally {
            BackgroundRuntime.stop(context)
            instrumentation.runOnMainSync { activity.finish() }
            BackgroundRuntime.onRuntimeShutdown()
            Python.getInstance().getModule("mesh_chat.mobile_bridge").callAttr("shutdown")
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

    private fun exchange(nativeOffers: Boolean, earlyIceFailure: Boolean = false, repeatedMedia: Boolean = false) {
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
        if (JSONObject(initialized).getJSONObject("result").optJSONObject("profile") == null) {
            command("create_profile", JSONObject().put("display_name", "WebRTC CI"))
        }
        fun injectEarlyIceFailure() {
            // Deterministic callback ordering regression: the production queue
            // must preserve this real peer until the signed answer is returned.
            // The test injects the notification, not a carrier/network failure.
            module.callAttr("native_webrtc_event", "ice", id, "failed")
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
            while (System.nanoTime() < deadline) {
                val events = JSONObject(module.callAttr("drain_events").toString()).getJSONArray("result")
                for (index in 0 until events.length()) {
                    val event = events.getJSONObject(index)
                    if (event.optString("event") == "webrtc_native_state" &&
                        event.optString("session_id") == id && event.optString("state") == "ice" &&
                        event.optString("detail") == "failed") return
                }
                Thread.sleep(20)
            }
            fail("The native ICE failure callback was not processed")
        }
        try {
            instrumentation.runOnMainSync {
                browser = WebView(context)
                browser.settings.javaScriptEnabled = true
                if (repeatedMedia) browser.settings.mediaPlaybackRequiresUserGesture = false
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
                    window.mediaCycle = async (media, cycle) => {
                      // Real Chromium RTP with generated tracks: no hardware
                      // microphone/camera, app media lifecycle or cellular NAT
                      // is simulated by this engine coexistence test.
                      const audio = new AudioContext();
                      const oscillator = audio.createOscillator();
                      const destination = audio.createMediaStreamDestination();
                      oscillator.connect(destination); oscillator.start();
                      const stream = destination.stream;
                      const left = new RTCPeerConnection({iceServers: []});
                      const right = new RTCPeerConnection({iceServers: []});
                      let frames = null;
                      const gatherMedia = peer => new Promise((resolve, reject) => {
                        if (peer.iceGatheringState === 'complete') return resolve();
                        const timer = setTimeout(() => reject(new Error('Media ICE gathering timed out')), 10000);
                        peer.addEventListener('icegatheringstatechange', () => {
                          if (peer.iceGatheringState === 'complete') { clearTimeout(timer); resolve(); }
                        });
                      });
                      try {
                        await audio.resume();
                        if (media === 'video') {
                          const canvas = document.createElement('canvas');
                          canvas.width = 160; canvas.height = 120;
                          const paint = canvas.getContext('2d');
                          const draw = () => { paint.fillStyle = Date.now() % 2 ? 'red' : 'blue'; paint.fillRect(0,0,160,120); };
                          draw(); frames = setInterval(draw, 100);
                          stream.addTrack(canvas.captureStream(10).getVideoTracks()[0]);
                        }
                        for (const track of stream.getTracks()) {
                          left.addTrack(track, stream); right.addTrack(track, stream);
                        }
                        await left.setLocalDescription(await left.createOffer()); await gatherMedia(left);
                        await right.setRemoteDescription(left.localDescription);
                        await right.setLocalDescription(await right.createAnswer()); await gatherMedia(right);
                        await left.setRemoteDescription(right.localDescription);
                        const kinds = media === 'video' ? ['audio','video'] : ['audio'];
                        const receiving = async peer => {
                          const stats = [...(await peer.getStats()).values()];
                          return kinds.every(kind => stats.some(row => row.type === 'inbound-rtp' &&
                            (row.kind || row.mediaType) === kind && row.bytesReceived > 0 && row.packetsReceived > 0));
                        };
                        const deadline = Date.now() + 15000;
                        while (!(await receiving(left)) || !(await receiving(right))) {
                          if (Date.now() > deadline) throw new Error('Bidirectional ' + media + ' RTP did not flow');
                          await new Promise(resolve => setTimeout(resolve, 100));
                        }
                        channels['mesh-reticulum'].send(new Uint8Array([20,cycle]));
                        const finish = new Promise(resolve => { window.finishMedia = resolve; });
                        report('media-active', cycle);
                        await finish;
                      } finally {
                        left.close(); right.close();
                        stream.getTracks().forEach(track => track.stop());
                        if (frames !== null) clearInterval(frames);
                        oscillator.stop(); await audio.close();
                      }
                      if (pc.connectionState !== 'connected' || channels['mesh-reticulum'].readyState !== 'open') {
                        throw new Error('Media teardown retired the messaging carrier');
                      }
                      channels['mesh-reticulum'].send(new Uint8Array([30,cycle]));
                      report('media-closed', cycle);
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
                val browserSdp = results.await("sdp")
                val fingerprint = browserSdp.lineSequence().first { it.startsWith("a=fingerprint:") }
                    .removePrefix("a=fingerprint:").trim()
                val offer = command("webrtc_onboarding_offer", JSONObject()
                    .put("sdp", browserSdp).put("dtls_fingerprint", fingerprint))
                val document = offer.getString("document")
                val preview = command("verify_webrtc_onboarding_offer", JSONObject().put("document", document))
                val native = command("native_webrtc_accept", payload.put("offer_sdp", preview.getString("sdp")))
                assertTrue(native.getString("fingerprint").startsWith("sha-256 "))
                if (earlyIceFailure) injectEarlyIceFailure()
                command("native_webrtc_bind_onboarding", JSONObject()
                    .put("session_id", id).put("offer_document", document))
                val nativeSdp = native.getString("sdp")
                val completeSdp = if (nativeSdp.lineSequence().any { it.trim() == "a=end-of-candidates" }) nativeSdp
                    else nativeSdp.trimEnd() + "\r\na=end-of-candidates\r\n"
                val answer = command("webrtc_onboarding_answer", JSONObject()
                    .put("offer_document", document).put("sdp", completeSdp)
                    .put("dtls_fingerprint", native.getString("fingerprint")))
                val verified = command("verify_webrtc_onboarding_answer", JSONObject()
                    .put("offer_document", document).put("answer_document", answer.getString("document")))
                if (earlyIceFailure) injectEarlyIceFailure()
                js("return finish(${JSONObject.quote(verified.getString("sdp"))})")
            }
            awaitStats(id) { it.optBoolean("attached") && it.optString("ice_connection_state") in setOf("connected", "completed") }
            js("return probe()")
            results.await("sent")
            awaitStats(id) { it.optLong("received_packets") >= 1 && it.optLong("received_controls") >= 1 }
            assertTrue(NativeWebRtcHost.send(id, byteArrayOf(4, 5, 6)))
            assertEquals("4,5,6", results.await("mesh-reticulum"))
            assertTrue(NativeWebRtcHost.sendControl(id, control, "probe-reply"))
            assertEquals("probe-reply", results.await(control, "probe-reply"))
            if (repeatedMedia) {
                for ((cycle, media) in listOf("audio", "video", "audio", "video").withIndex()) {
                    val before = command("native_webrtc_stats", JSONObject().put("session_id", id)).getLong("received_packets")
                    js("return mediaCycle(${JSONObject.quote(media)}, $cycle)")
                    results.await("media-active", cycle.toString())
                    awaitStats(id) { it.optBoolean("attached") && it.optLong("received_packets") > before }
                    assertTrue(NativeWebRtcHost.send(id, byteArrayOf(40, cycle.toByte())))
                    assertEquals("40,$cycle", results.await("mesh-reticulum", "40,$cycle"))
                    js("finishMedia()")
                    results.await("media-closed", cycle.toString())
                    awaitStats(id) { it.optBoolean("attached") && it.optLong("received_packets") >= before + 2 &&
                        it.optString("ice_connection_state") in setOf("connected", "completed") }
                    assertTrue(NativeWebRtcHost.send(id, byteArrayOf(50, cycle.toByte())))
                    assertEquals("50,$cycle", results.await("mesh-reticulum", "50,$cycle"))
                }
            }
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
