package com.meshchat.runtime

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import com.chaquo.python.Python
import org.json.JSONArray
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import java.nio.ByteBuffer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicLong

/**
 * Native WebRTC data-channel ownership for the background availability mode.
 *
 * The WebView is not in this data path. Python calls the JSON methods below
 * through Chaquopy, signs the returned SDP with the existing identity, and
 * attaches one Reticulum WebRTCInterface per open mesh-reticulum channel.
 *
 * This host is intentionally data-only; audio/video calls remain in the
 * WebView + CallService path.
 */
object NativeWebRtcHost {
    private const val TAG = "MeshChatNativeWebRtc"
    private const val MAX_SESSIONS = 16
    private const val GATHER_TIMEOUT_SECONDS = 20L
    private const val MESSAGE_LIMIT = 1064
    private const val CONTROL_LIMIT = 65_536

    private data class ChannelSpec(
        val label: String,
        val binary: Boolean,
        val ordered: Boolean,
    )

    private class Session(
        val pc: PeerConnection,
        val role: String,
    ) {
        val channels = ConcurrentHashMap<String, DataChannel>()
        @Volatile var expectedChannels: Set<String> = emptySet()
        @Volatile var gathering: CountDownLatch? = null
        @Volatile var closed = false
        val receivedPackets = AtomicLong()
        val receivedControls = AtomicLong()
    }

    private val sessions = ConcurrentHashMap<String, Session>()
    private val mainHandler = Handler(Looper.getMainLooper())
    @Volatile private var factory: PeerConnectionFactory? = null
    @Volatile private var initialized = false

    /**
     * Store the application context without loading libwebrtc. This runs during
     * normal app startup; the native library and PeerConnectionFactory are
     * created only when a native session is actually requested.
     */
    @JvmStatic
    fun attachContext(context: Context) {
        NativeWebRtcContext.attach(context)
    }

    @JvmStatic
    fun initialize(context: Context) {
        attachContext(context)
        ensureInitialized()
    }

    private fun ensureInitialized() {
        if (initialized) return
        synchronized(this) {
            if (initialized) return
            val context = NativeWebRtcContext.get()
                ?: throw IllegalStateException("native_webrtc_context_missing")
            onMain {
                PeerConnectionFactory.initialize(
                    PeerConnectionFactory.InitializationOptions.builder(context)
                        .setEnableInternalTracer(false)
                        .createInitializationOptions(),
                )
                factory = PeerConnectionFactory.builder()
                    .createPeerConnectionFactory()
            }
            initialized = true
        }
    }

    @JvmStatic
    fun createOffer(sessionId: String, iceJson: String, channelsJson: String): String {
        return try {
            val factory = requireFactory()
            if (sessions.size >= MAX_SESSIONS) return error("native_webrtc_session_limit")
            val specs = parseChannels(channelsJson)
            if (specs.none { it.label == "mesh-reticulum" && it.binary }) {
                return error("native_webrtc_missing_data_channel")
            }
            val pc = createPeerConnection(factory, iceJson, sessionId, "offer")
            val session = Session(pc, "offer")
            sessions[sessionId] = session
            for (spec in specs) {
                val channel = pc.createDataChannel(spec.label, dataChannelInit(spec))
                    ?: throw IllegalStateException("native_webrtc_channel_failed")
                registerChannel(sessionId, session, spec.label, channel)
            }
            val offer = createLocalOffer(sessionId, session)
            val description = offer.description
            if (description.isBlank()) return error("native_webrtc_offer_empty")
            success(description)
        } catch (error: Throwable) {
            Log.e(TAG, "createOffer failed (${error.javaClass.simpleName})")
            close(sessionId)
            error("native_webrtc_offer_failed")
        }
    }

    @JvmStatic
    fun acceptOffer(
        sessionId: String,
        offerSdp: String,
        iceJson: String,
        expectedChannelsJson: String,
    ): String {
        return try {
            val factory = requireFactory()
            if (sessions.size >= MAX_SESSIONS) return error("native_webrtc_session_limit")
            val specs = parseChannels(expectedChannelsJson)
            if (specs.none { it.label == "mesh-reticulum" && it.binary }) {
                return error("native_webrtc_missing_data_channel")
            }
            val expected = specs.map { it.label }.toSet()
            val pc = createPeerConnection(factory, iceJson, sessionId, "answer")
            val session = Session(pc, "answer")
            sessions[sessionId] = session
            session.expectedChannels = expected
            awaitSetRemote(pc, SessionDescription(SessionDescription.Type.OFFER, offerSdp))
            val answer = awaitCreateAnswer(pc)
            awaitSetLocal(pc, answer)
            awaitGather(session)
            val description = pc.localDescription?.description
            if (description.isNullOrBlank()) return error("native_webrtc_answer_empty")
            success(description)
        } catch (error: Throwable) {
            Log.e(TAG, "acceptOffer failed (${error.javaClass.simpleName})")
            close(sessionId)
            error("native_webrtc_answer_failed")
        }
    }

    @JvmStatic
    fun applyAnswer(sessionId: String, answerSdp: String): String {
        return try {
            val session = sessions[sessionId] ?: return error("native_webrtc_session_missing")
            synchronized(session) {
                awaitSetRemote(session.pc, SessionDescription(SessionDescription.Type.ANSWER, answerSdp))
            }
            success("")
        } catch (error: Throwable) {
            Log.e(TAG, "applyAnswer failed (${error.javaClass.simpleName})")
            error("native_webrtc_apply_failed")
        }
    }

    @JvmStatic
    fun restartIce(sessionId: String): String {
        return try {
            val session = sessions[sessionId] ?: return error("native_webrtc_session_missing")
            synchronized(session) {
                val offer = createLocalOffer(sessionId, session)
                success(offer.description ?: "")
            }
        } catch (error: Throwable) {
            Log.e(TAG, "restartIce failed (${error.javaClass.simpleName})")
            error("native_webrtc_restart_failed")
        }
    }

    @JvmStatic
    fun send(sessionId: String, packet: ByteArray): Boolean {
        if (packet.isEmpty() || packet.size > MESSAGE_LIMIT) return false
        val session = sessions[sessionId] ?: return false
        val channel = session.channels["mesh-reticulum"] ?: return false
        return try {
            synchronized(channel) {
                channel.send(DataChannel.Buffer(ByteBuffer.wrap(packet), true))
            }
        } catch (error: Throwable) {
            Log.e(TAG, "send failed (${error.javaClass.simpleName})")
            false
        }
    }

    @JvmStatic
    fun sendControl(sessionId: String, label: String, text: String): Boolean {
        if (text.isEmpty() || text.length > CONTROL_LIMIT) return false
        if (label !in setOf("mesh-onboarding", "meshchat-reconnect")) return false
        val session = sessions[sessionId] ?: return false
        val channel = session.channels[label] ?: return false
        return try {
            synchronized(channel) {
                channel.send(DataChannel.Buffer(ByteBuffer.wrap(text.toByteArray(Charsets.UTF_8)), false))
            }
        } catch (error: Throwable) {
            Log.e(TAG, "sendControl failed (${error.javaClass.simpleName})")
            false
        }
    }

    @JvmStatic
    fun close(sessionId: String) {
        val session = sessions.remove(sessionId) ?: return
        session.closed = true
        for (channel in session.channels.values) {
            try { channel.close() } catch (_: Throwable) { }
            try { channel.dispose() } catch (_: Throwable) { }
        }
        session.channels.clear()
        try { session.pc.close() } catch (_: Throwable) { }
        try { session.pc.dispose() } catch (_: Throwable) { }
        notifyPython("closed", sessionId, "")
    }

    @JvmStatic
    fun closeAll() {
        for (sessionId in sessions.keys.toList()) close(sessionId)
    }

    @JvmStatic
    fun stats(sessionId: String): String {
        val session = sessions[sessionId] ?: return error("native_webrtc_session_missing")
        val result = JSONObject()
            .put("ice_connection_state", session.pc.iceConnectionState().name.lowercase())
            .put("ice_gathering_state", session.pc.iceGatheringState().name.lowercase())
            .put("data_channel_state", session.channels["mesh-reticulum"]?.state()?.name?.lowercase() ?: "missing")
            .put("channels", JSONArray(session.channels.keys.toList()))
            .put("received_packets", session.receivedPackets.get())
            .put("received_controls", session.receivedControls.get())
        return JSONObject().put("ok", true).put("result", result).toString()
    }

    private fun createPeerConnection(
        factory: PeerConnectionFactory,
        iceJson: String,
        sessionId: String,
        role: String,
    ): PeerConnection {
        val ice = JSONObject(iceJson)
        val configuration = PeerConnection.RTCConfiguration(iceServers(ice))
        configuration.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        configuration.bundlePolicy = PeerConnection.BundlePolicy.MAXBUNDLE
        configuration.rtcpMuxPolicy = PeerConnection.RtcpMuxPolicy.REQUIRE
        configuration.continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
        configuration.iceTransportsType = if (ice.optString("iceTransportPolicy") == "relay") {
            PeerConnection.IceTransportsType.RELAY
        } else {
            PeerConnection.IceTransportsType.ALL
        }
        return factory.createPeerConnection(configuration, observer(sessionId, role))
            ?: throw IllegalStateException("native_webrtc_peer_failed")
    }

    private fun iceServers(ice: JSONObject): List<PeerConnection.IceServer> {
        val values = ice.optJSONArray("iceServers") ?: JSONArray()
        val servers = mutableListOf<PeerConnection.IceServer>()
        for (index in 0 until values.length()) {
            val item = values.optJSONObject(index) ?: continue
            val urls = item.optJSONArray("urls") ?: continue
            for (urlIndex in 0 until urls.length()) {
                val url = urls.optString(urlIndex)
                if (!url.startsWith("stun:") && !url.startsWith("turn:") && !url.startsWith("turns:")) continue
                val builder = PeerConnection.IceServer.builder(url)
                item.optString("username").takeIf { it.isNotEmpty() }?.let(builder::setUsername)
                item.optString("credential").takeIf { it.isNotEmpty() }?.let(builder::setPassword)
                servers += builder.createIceServer()
            }
        }
        return servers
    }

    private fun observer(sessionId: String, role: String): PeerConnection.Observer =
        object : PeerConnection.Observer {
            override fun onSignalingChange(state: PeerConnection.SignalingState) {
                notifyPython("signaling", sessionId, state.name.lowercase())
            }

            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                notifyPython("ice", sessionId, state.name.lowercase())
            }

            override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit

            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
                notifyPython("gathering", sessionId, state.name.lowercase())
                if (state == PeerConnection.IceGatheringState.COMPLETE) {
                    sessions[sessionId]?.gathering?.countDown()
                }
            }

            override fun onIceCandidate(candidate: IceCandidate) = Unit

            override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) = Unit

            override fun onAddStream(stream: MediaStream) = Unit

            override fun onRemoveStream(stream: MediaStream) = Unit

            override fun onDataChannel(channel: DataChannel) {
                val session = sessions[sessionId] ?: run {
                    try { channel.close() } catch (_: Throwable) { }
                    return
                }
                val label = channel.label()
                if (label !in session.expectedChannels) {
                    try { channel.close() } catch (_: Throwable) { }
                    return
                }
                if (label !in setOf("mesh-reticulum", "mesh-onboarding", "meshchat-reconnect")) {
                    try { channel.close() } catch (_: Throwable) { }
                    return
                }
                registerChannel(sessionId, session, label, channel)
            }

            override fun onRenegotiationNeeded() = Unit

            override fun onAddTrack(receiver: RtpReceiver, streams: Array<MediaStream>) = Unit
        }

    private fun registerChannel(
        sessionId: String,
        session: Session,
        label: String,
        channel: DataChannel,
    ) {
        if (session.channels.putIfAbsent(label, channel) != null) {
            try { channel.close() } catch (_: Throwable) { }
            return
        }
        channel.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(previousAmount: Long) = Unit

            override fun onStateChange() {
                val state = channel.state().name.lowercase()
                notifyPython("channel", sessionId, "$label:$state")
                if (label == "mesh-reticulum" && channel.state() == DataChannel.State.OPEN) {
                    notifyPython("open", sessionId, channel.label())
                }
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                val data = buffer.data
                val limit = if (label == "mesh-reticulum") MESSAGE_LIMIT else CONTROL_LIMIT
                if (!data.hasRemaining() || data.remaining() > limit) return
                val bytes = ByteArray(data.remaining())
                data.get(bytes)
                val encoded = Base64.encodeToString(bytes, Base64.NO_WRAP)
                if (label == "mesh-reticulum") {
                    session.receivedPackets.incrementAndGet()
                    notifyPython("message", sessionId, encoded)
                } else {
                    session.receivedControls.incrementAndGet()
                    notifyPython("control", sessionId, "$label:$encoded")
                }
            }
        })
        if (channel.state() == DataChannel.State.OPEN) {
            notifyPython("channel", sessionId, "$label:open")
            if (label == "mesh-reticulum") notifyPython("open", sessionId, label)
        }
    }

    private fun createLocalOffer(sessionId: String, session: Session): SessionDescription {
        val pc = session.pc
        val constraints = MediaConstraints()
        val offer = awaitSdp { observer -> pc.createOffer(observer, constraints) }
        awaitSetLocal(pc, offer)
        awaitGather(session)
        return pc.localDescription ?: offer
    }

    private fun awaitCreateAnswer(pc: PeerConnection): SessionDescription {
        val constraints = MediaConstraints()
        return awaitSdp { observer -> pc.createAnswer(observer, constraints) }
    }

    private fun awaitSetLocal(pc: PeerConnection, sdp: SessionDescription) {
        val latch = CountDownLatch(1)
        val failure = AtomicReference<Throwable>()
        pc.setLocalDescription(object : SdpObserver {
            override fun onCreateSuccess(description: SessionDescription?) = Unit
            override fun onSetSuccess() = latch.countDown()
            override fun onCreateFailure(error: String?) {
                failure.set(IllegalStateException(error ?: "native_webrtc_set_local_failed"))
                latch.countDown()
            }
            override fun onSetFailure(error: String?) {
                failure.set(IllegalStateException(error ?: "native_webrtc_set_local_failed"))
                latch.countDown()
            }
        }, sdp)
        if (!latch.await(GATHER_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            throw IllegalStateException("native_webrtc_set_local_timeout")
        }
        failure.get()?.let { throw it }
    }

    private fun awaitSetRemote(pc: PeerConnection, sdp: SessionDescription) {
        val latch = CountDownLatch(1)
        val failure = AtomicReference<Throwable>()
        pc.setRemoteDescription(object : SdpObserver {
            override fun onCreateSuccess(description: SessionDescription?) = Unit
            override fun onSetSuccess() = latch.countDown()
            override fun onCreateFailure(error: String?) = Unit
            override fun onSetFailure(error: String?) {
                failure.set(IllegalStateException(error ?: "native_webrtc_set_remote_failed"))
                latch.countDown()
            }
        }, sdp)
        if (!latch.await(GATHER_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            throw IllegalStateException("native_webrtc_set_remote_timeout")
        }
        failure.get()?.let { throw it }
    }

    private fun awaitSdp(create: (SdpObserver) -> Unit): SessionDescription {
        val latch = CountDownLatch(1)
        val result = AtomicReference<SessionDescription>()
        val failure = AtomicReference<Throwable>()
        create(object : SdpObserver {
            override fun onCreateSuccess(description: SessionDescription?) {
                if (description == null) {
                    failure.set(IllegalStateException("native_webrtc_sdp_empty"))
                } else {
                    result.set(description)
                }
                latch.countDown()
            }
            override fun onSetSuccess() = Unit
            override fun onCreateFailure(error: String?) {
                failure.set(IllegalStateException(error ?: "native_webrtc_sdp_failed"))
                latch.countDown()
            }
            override fun onSetFailure(error: String?) = Unit
        })
        if (!latch.await(GATHER_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            throw IllegalStateException("native_webrtc_sdp_timeout")
        }
        failure.get()?.let { throw it }
        return result.get() ?: throw IllegalStateException("native_webrtc_sdp_empty")
    }

    private fun awaitGather(session: Session) {
        val latch = CountDownLatch(1)
        session.gathering = latch
        if (session.pc.iceGatheringState() == PeerConnection.IceGatheringState.COMPLETE) {
            latch.countDown()
        }
        latch.await(GATHER_TIMEOUT_SECONDS, TimeUnit.SECONDS)
    }

    private fun parseChannels(raw: String): List<ChannelSpec> {
        val values = JSONArray(raw)
        val specs = mutableListOf<ChannelSpec>()
        for (index in 0 until values.length()) {
            val item = values.optJSONObject(index) ?: continue
            val label = item.optString("label")
            if (label !in setOf("mesh-reticulum", "mesh-onboarding", "meshchat-reconnect")) continue
            specs += ChannelSpec(
                label = label,
                binary = item.optBoolean("binary", label == "mesh-reticulum"),
                ordered = item.optBoolean("ordered", true),
            )
        }
        return specs
    }

    private fun dataChannelInit(spec: ChannelSpec): DataChannel.Init =
        DataChannel.Init().apply {
            ordered = spec.ordered
            maxRetransmits = -1
        }

    private fun requireFactory(): PeerConnectionFactory {
        ensureInitialized()
        return factory ?: throw IllegalStateException("native_webrtc_not_initialized")
    }

    private fun success(sdp: String): String = JSONObject()
        .put("ok", true)
        .put("sdp", sdp)
        .put("fingerprint", fingerprint(sdp))
        .toString()

    private fun error(code: String): String =
        JSONObject().put("ok", false).put("error", code).toString()

    private fun fingerprint(sdp: String): String {
        val match = Regex("(?im)^a=fingerprint:sha-256\\s+([0-9a-f:]{95})\\s*$").find(sdp)
        return match?.groupValues?.get(1)?.let { "sha-256 ${it.uppercase()}" } ?: ""
    }

    private fun notifyPython(event: String, sessionId: String, data: String) {
        try {
            Python.getInstance()
                .getModule("mesh_chat.mobile_bridge")
                .callAttr("native_webrtc_event", event, sessionId, data)
        } catch (error: Throwable) {
            Log.e(TAG, "python callback failed (${error.javaClass.simpleName})")
        }
    }

    private fun <T> onMain(block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return block()
        val latch = CountDownLatch(1)
        val result = AtomicReference<T>()
        val failure = AtomicReference<Throwable>()
        mainHandler.post {
            try {
                result.set(block())
            } catch (error: Throwable) {
                failure.set(error)
            } finally {
                latch.countDown()
            }
        }
        if (!latch.await(30, TimeUnit.SECONDS)) {
            throw IllegalStateException("native_webrtc_main_timeout")
        }
        failure.get()?.let { throw it }
        return result.get() as T
    }
}
