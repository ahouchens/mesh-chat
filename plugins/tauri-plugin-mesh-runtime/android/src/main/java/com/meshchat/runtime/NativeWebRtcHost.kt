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
import org.webrtc.NetworkMonitor
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RTCStats
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import java.nio.ByteBuffer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicBoolean
import java.security.MessageDigest
import java.net.InetAddress
import java.util.UUID

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
        val lease: NativeSessionReservations.Lease,
    ) {
        val id get() = lease.id
        lateinit var pc: PeerConnection
        val channels = ConcurrentHashMap<String, DataChannel>()
        @Volatile var expectedChannels: Set<String> = emptySet()
        @Volatile var gathering: CountDownLatch? = null
        @Volatile var closed = false
        val disposed = CountDownLatch(1)
        val receivedPackets = AtomicLong()
        val receivedControls = AtomicLong()
        val receivedBytes = AtomicLong()
        val enqueuedPackets = AtomicLong()
        val enqueuedControls = AtomicLong()
        val enqueuedBytes = AtomicLong()
        val sampleSequence = AtomicLong()
        val sampling = AtomicBoolean()
        val callbacks = NativeCallbackQueue({ notifyPython("overflow", id, "") })
    }

    private val sessions = ConcurrentHashMap<String, Session>()
    private val reservations = NativeSessionReservations(MAX_SESSIONS)
    private val adapterEpoch = UUID.randomUUID().toString().replace("-", "")
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
        return createReserved(sessionId) { lease ->
            retryEmptyDescription(lease) { createOfferAttempt(lease, iceJson, channelsJson) }
        }
    }

    private fun createOfferAttempt(lease: NativeSessionReservations.Lease, iceJson: String, channelsJson: String): String {
        val sessionId = lease.id
        return try {
            val factory = requireFactory()
            val specs = parseChannels(channelsJson)
            if (specs.none { it.label == "mesh-reticulum" && it.binary }) {
                return error("native_webrtc_missing_data_channel")
            }
            val session = allocateSession(factory, iceJson, lease)
            val pc = session.pc
            synchronized(session) {
                for (spec in specs) {
                    val channel = pc.createDataChannel(spec.label, dataChannelInit(spec))
                        ?: throw IllegalStateException("native_webrtc_channel_failed")
                    registerChannel(session, spec.label, channel)
                }
                val offer = createLocalOffer(session)
                val description = offer.description
                check(!session.closed) { "native_webrtc_session_closed" }
                check(description.isNotBlank()) { "native_webrtc_offer_empty" }
                success(description)
            }
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
        return createReserved(sessionId) { lease ->
            retryEmptyDescription(lease) {
                acceptOfferAttempt(lease, offerSdp, iceJson, expectedChannelsJson)
            }
        }
    }

    private fun acceptOfferAttempt(
        lease: NativeSessionReservations.Lease,
        offerSdp: String,
        iceJson: String,
        expectedChannelsJson: String,
    ): String {
        val sessionId = lease.id
        return try {
            val factory = requireFactory()
            val specs = parseChannels(expectedChannelsJson)
            if (specs.none { it.label == "mesh-reticulum" && it.binary }) {
                return error("native_webrtc_missing_data_channel")
            }
            val expected = specs.map { it.label }.toSet()
            val session = allocateSession(factory, iceJson, lease)
            val pc = session.pc
            session.expectedChannels = expected
            synchronized(session) {
                awaitSetRemote(pc, SessionDescription(SessionDescription.Type.OFFER, offerSdp))
                val answer = awaitCreateAnswer(pc)
                awaitSetLocal(pc, answer)
                awaitGather(session)
                val description = pc.localDescription?.description
                check(!session.closed) { "native_webrtc_session_closed" }
                check(!description.isNullOrBlank()) { "native_webrtc_answer_empty" }
                success(description)
            }
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
                check(!session.closed) { "native_webrtc_session_closed" }
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
                check(!session.closed) { "native_webrtc_session_closed" }
                val offer = createLocalOffer(session)
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
        return try {
            synchronized(session) {
                if (session.closed) return false
                val channel = session.channels["mesh-reticulum"] ?: return false
                channel.send(DataChannel.Buffer(ByteBuffer.wrap(packet), true)).also { accepted ->
                    if (accepted) {
                        session.enqueuedPackets.incrementAndGet()
                        session.enqueuedBytes.addAndGet(packet.size.toLong())
                    }
                }
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
        return try {
            synchronized(session) {
                if (session.closed) return false
                val channel = session.channels[label] ?: return false
                val bytes = text.toByteArray(Charsets.UTF_8)
                channel.send(DataChannel.Buffer(ByteBuffer.wrap(bytes), false)).also { accepted ->
                    if (accepted) {
                        session.enqueuedControls.incrementAndGet()
                        session.enqueuedBytes.addAndGet(bytes.size.toLong())
                    }
                }
            }
        } catch (error: Throwable) {
            Log.e(TAG, "sendControl failed (${error.javaClass.simpleName})")
            false
        }
    }

    @JvmStatic
    fun close(sessionId: String) {
        reservations.cancel(sessionId) ?: return
        val session = sessions[sessionId]
        if (session != null) retireSession(session)
        notifyPython("closed", sessionId, "")
    }

    private fun retireSession(session: Session) {
        sessions.remove(session.id, session)
        session.closed = true
        // Retire routing immediately. Disposal may wait for an in-flight SDP
        // operation, so it must never block Android's UI/Service thread.
        session.callbacks.close {
          synchronized(session) {
            for (channel in session.channels.values) {
                // Fence callbacks before disposing their native pointer.
                try { channel.unregisterObserver() } catch (_: Throwable) { }
                disposeUnusedChannel(channel)
            }
            session.channels.clear()
            try { session.pc.close() } catch (_: Throwable) { }
            // A failed disposal retains capacity; starting more peers would
            // hide an unbounded native leak behind an empty routing map.
            try {
                session.pc.dispose()
                reservations.disposed(session.lease)
                session.disposed.countDown()
            } catch (_: Throwable) {
                notifyPython("overflow", session.id, "")
            }
          }
        }
    }

    @JvmStatic
    fun closeAll() {
        for (sessionId in reservations.ids()) close(sessionId)
    }

    /** Private qualification accounting includes asynchronous disposal leases. */
    @JvmStatic
    fun resourceAccounting(): String {
        val counts = reservations.accounting()
        val result = JSONObject().put("v", 1).put("complete", true)
            .put("semantics", "native_allocation_leases")
            .put("availability", JSONObject().apply {
                for (name in counts.keys) put(name, true)
            })
        for ((name, count) in counts) result.put(name, count)
        return JSONObject().put("ok", true).put("result", result).toString()
    }

    @JvmStatic
    fun stats(sessionId: String): String {
        val session = sessions[sessionId] ?: return error("native_webrtc_session_missing")
        synchronized(session) {
        if (session.closed) return error("native_webrtc_session_missing")
        val result = JSONObject()
            .put("ice_connection_state", session.pc.iceConnectionState().name.lowercase())
            .put("ice_gathering_state", session.pc.iceGatheringState().name.lowercase())
            .put("data_channel_state", session.channels["mesh-reticulum"]?.state()?.name?.lowercase() ?: "missing")
            .put("channels", JSONArray(session.channels.keys.toList()))
            .put("received_packets", session.receivedPackets.get())
            .put("received_controls", session.receivedControls.get())
        return JSONObject().put("ok", true).put("result", result).toString()
        }
    }

    /** Trusted qualification only; absent stats never imply a selected path. */
    @JvmStatic
    fun pathEvidence(sessionId: String): String {
        if (Looper.myLooper() == Looper.getMainLooper()) return error("native_webrtc_inspection_wrong_thread")
        val session = sessions[sessionId] ?: return error("native_webrtc_session_missing")
        if (!isCurrent(session)) return error("native_webrtc_session_missing")
        if (!session.sampling.compareAndSet(false, true)) return error("native_webrtc_inspection_busy")
        val done = CountDownLatch(1)
        val result = AtomicReference<String>()
        try {
            synchronized(session) {
                if (!isCurrent(session)) {
                    session.sampling.set(false)
                    return error("native_webrtc_session_missing")
                }
                session.pc.getStats { report ->
                    try {
                        synchronized(session) {
                            if (isCurrent(session)) {
                                val application = JSONObject()
                                    .put("enqueued_packets", session.enqueuedPackets.get())
                                    .put("enqueued_controls", session.enqueuedControls.get())
                                    .put("enqueued_bytes", session.enqueuedBytes.get())
                                    .put("received_packets", session.receivedPackets.get())
                                    .put("received_controls", session.receivedControls.get())
                                    .put("received_bytes", session.receivedBytes.get())
                                val value = NativePathEvidence.sample(sessionId, adapterEpoch,
                                    session.sampleSequence.incrementAndGet(), System.nanoTime() / 1_000_000,
                                    session.pc.iceConnectionState().name.lowercase(),
                                    session.channels["mesh-reticulum"]?.state()?.name?.lowercase() ?: "missing",
                                    report.statsMap, application)
                                result.set(JSONObject().put("ok", true).put("result", value).toString())
                            }
                        }
                    } catch (_: Throwable) {
                        result.set(error("native_webrtc_inspection_failed"))
                    } finally {
                        session.sampling.set(false)
                        done.countDown()
                    }
                }
            }
            // A timed-out callback keeps its single sampling slot until it
            // actually completes; callers cannot queue unbounded native jobs.
            if (!done.await(2, TimeUnit.SECONDS)) return error("native_webrtc_inspection_timeout")
            if (!isCurrent(session)) return error("native_webrtc_session_missing")
            return result.get() ?: error("native_webrtc_session_missing")
        } catch (_: Throwable) {
            return error("native_webrtc_inspection_failed")
        }
    }

    private fun createPeerConnection(
        factory: PeerConnectionFactory,
        iceJson: String,
        session: Session,
    ): PeerConnection {
        val ice = JSONObject(iceJson)
        val configuration = PeerConnection.RTCConfiguration(iceServers(ice))
        configuration.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        configuration.bundlePolicy = PeerConnection.BundlePolicy.MAXBUNDLE
        configuration.rtcpMuxPolicy = PeerConnection.RtcpMuxPolicy.REQUIRE
        // Signaling sends a complete SDP, not incremental ICE candidates.
        // Continuous gathering never reports COMPLETE and makes awaitGather
        // consume its full timeout on every offer/answer. Mailbox recovery
        // creates a new native session to exchange fresh candidates.
        configuration.continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_ONCE
        configuration.iceTransportsType = if (ice.optString("iceTransportPolicy") == "relay") {
            PeerConnection.IceTransportsType.RELAY
        } else {
            PeerConnection.IceTransportsType.ALL
        }
        return factory.createPeerConnection(configuration, observer(session))
            ?: throw IllegalStateException("native_webrtc_peer_failed")
    }

    private fun createReserved(sessionId: String, create: (NativeSessionReservations.Lease) -> String): String {
        val lease = reservations.reserve(sessionId) ?: return error("native_webrtc_session_limit")
        try {
            val result = create(lease)
            if (!JSONObject(result).optBoolean("ok")) {
                close(sessionId)
                return result
            }
            if (!reservations.active(lease)) return error("native_webrtc_session_closed")
            return result
        } catch (_: Throwable) {
            close(sessionId)
            return error("native_webrtc_creation_failed")
        } finally {
            reservations.finishCreation(lease)
        }
    }

    private fun allocateSession(
        factory: PeerConnectionFactory,
        iceJson: String,
        lease: NativeSessionReservations.Lease,
    ): Session {
        check(reservations.beginAllocation(lease)) { "native_webrtc_session_closed" }
        val session = Session(lease)
        try {
            session.pc = createPeerConnection(factory, iceJson, session)
        } catch (failure: Throwable) {
            reservations.disposed(lease)
            session.callbacks.close { }
            throw failure
        }
        sessions[lease.id] = session
        if (!reservations.active(lease)) {
            retireSession(session)
            throw IllegalStateException("native_webrtc_session_closed")
        }
        return session
    }

    private fun isCurrent(session: Session): Boolean =
        !session.closed && sessions[session.id] === session && reservations.active(session.lease)

    private fun notifyCurrent(session: Session, event: String, data: String) {
        if (isCurrent(session)) notifyPython(event, session.id, data)
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

    private fun observer(session: Session): PeerConnection.Observer =
        object : PeerConnection.Observer {
            override fun onSignalingChange(state: PeerConnection.SignalingState) {
                notifyCurrent(session, "signaling", state.name.lowercase())
            }

            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                notifyCurrent(session, "ice", state.name.lowercase())
            }

            override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit

            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
                notifyCurrent(session, "gathering", state.name.lowercase())
                if (state == PeerConnection.IceGatheringState.COMPLETE) {
                    session.gathering?.countDown()
                }
            }

            override fun onIceCandidate(candidate: IceCandidate) = Unit

            override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) = Unit

            override fun onAddStream(stream: MediaStream) = Unit

            override fun onRemoveStream(stream: MediaStream) = Unit

            override fun onDataChannel(channel: DataChannel) {
                if (!isCurrent(session)) {
                    disposeUnusedChannel(channel)
                    return
                }
                enqueueChannelEvent(session, { disposeUnusedChannel(channel) }) {
                    val label = channel.label()
                    if (label !in session.expectedChannels || label !in setOf("mesh-reticulum", "mesh-onboarding", "meshchat-reconnect")) {
                        disposeUnusedChannel(channel)
                        return@enqueueChannelEvent
                    }
                    registerChannel(session, label, channel)
                }
            }

            override fun onRenegotiationNeeded() = Unit

            override fun onAddTrack(receiver: RtpReceiver, streams: Array<MediaStream>) = Unit
        }

    private fun registerChannel(
        session: Session,
        label: String,
        channel: DataChannel,
    ) {
        if (session.channels.putIfAbsent(label, channel) != null) {
            disposeUnusedChannel(channel)
            return
        }
        channel.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(previousAmount: Long) = Unit

            override fun onStateChange() {
                // A signaling-thread callback can outlive close()/dispose().
                // Read native state later under the same lifetime lock used
                // by stats, sends and disposal, without blocking signaling.
                enqueueChannelEvent(session) {
                    if (session.channels[label] !== channel) return@enqueueChannelEvent
                    val state = channel.state()
                    notifyCurrent(session, "channel", "$label:${state.name.lowercase()}")
                    if (label == "mesh-reticulum" && state == DataChannel.State.OPEN) {
                        notifyCurrent(session, "open", label)
                    }
                }
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                if (!isCurrent(session)) return
                val data = buffer.data
                val limit = if (label == "mesh-reticulum") MESSAGE_LIMIT else CONTROL_LIMIT
                if (!data.hasRemaining() || data.remaining() > limit) return
                val bytes = ByteArray(data.remaining())
                data.get(bytes)
                session.receivedBytes.addAndGet(bytes.size.toLong())
                val encoded = Base64.encodeToString(bytes, Base64.NO_WRAP)
                if (label == "mesh-reticulum") {
                    session.receivedPackets.incrementAndGet()
                    notifyCurrent(session, "message", encoded)
                } else {
                    session.receivedControls.incrementAndGet()
                    notifyCurrent(session, "control", "$label:$encoded")
                }
            }
        })
        if (channel.state() == DataChannel.State.OPEN) {
            notifyCurrent(session, "channel", "$label:open")
            if (label == "mesh-reticulum") notifyCurrent(session, "open", label)
        }
    }

    private fun createLocalOffer(session: Session): SessionDescription {
        val pc = session.pc
        val constraints = MediaConstraints()
        val offer = awaitSdp { observer -> pc.createOffer(observer, constraints) }
        awaitSetLocal(pc, offer)
        awaitGather(session)
        return pc.localDescription ?: offer
    }

    private fun disposeUnusedChannel(channel: DataChannel) {
        try { channel.close() } catch (_: Throwable) { }
        try { channel.dispose() } catch (_: Throwable) { }
    }

    private fun enqueueChannelEvent(session: Session, discarded: () -> Unit = {}, block: () -> Unit) {
        if (!isCurrent(session)) { discarded(); return }
        session.callbacks.submit(discarded) {
            synchronized(session) {
                if (isCurrent(session)) block() else discarded()
            }
        }
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

    private fun retryEmptyDescription(lease: NativeSessionReservations.Lease, create: () -> String): String {
        // Android's network monitor can still be initializing when one-shot
        // gathering completes without candidates. Such SDP cannot bootstrap
        // our non-trickle exchange. Recreate the peer after a short bounded
        // delay, keeping its ICE policy (including relay-only) unchanged.
        val monitor = try {
            ensureInitialized()
            NetworkMonitor.getInstance().also {
                it.startMonitoring(requireNotNull(NativeWebRtcContext.get()), "")
            }
        } catch (_: Throwable) {
            return error("native_webrtc_network_monitor_failed")
        }
        try {
            val retryUntil = System.nanoTime() + TimeUnit.SECONDS.toNanos(2)
            repeat(3) { attempt ->
                if (!reservations.active(lease)) return error("native_webrtc_session_closed")
                val result = create()
                val value = JSONObject(result)
                if (!value.optBoolean("ok") || value.optString("sdp").lineSequence().any { it.startsWith("a=candidate:") }) {
                    return result
                }
                val session = sessions[lease.id] ?: return error("native_webrtc_session_closed")
                retireSession(session)
                // The same reservation is retained across this bounded
                // gathering fallback. Cancellation cannot resurrect it.
                if (!session.disposed.await(2, TimeUnit.SECONDS)) {
                    return error("native_webrtc_disposal_timeout")
                }
                // Do not multiply the full gathering timeout when an unavailable
                // TURN server or network genuinely has no usable candidates.
                if (System.nanoTime() >= retryUntil) return error("native_webrtc_no_candidates")
                if (attempt < 2) Thread.sleep(500)
            }
            return error("native_webrtc_no_candidates")
        } catch (_: InterruptedException) {
            close(lease.id)
            Thread.currentThread().interrupt()
            return error("native_webrtc_session_closed")
        } finally {
            // Retain the monitor while replacing an empty peer, or closing the
            // last native observer resets network discovery on every retry.
            // Successful peers retain their own reference after this is freed.
            monitor.stopMonitoring()
        }
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

/** Pure conversion of current libwebrtc statistics, also used by JVM tests. */
internal object NativePathEvidence {
    private const val MAX_INTEGER = 9007199254740991L

    fun sample(resource: String, epoch: String, sequence: Long, sampledAt: Long,
               ice: String, channel: String, stats: Map<String, RTCStats>, application: JSONObject): JSONObject {
        val transports = stats.values.filter { it.type == "transport" }
        val selected = transports.mapNotNull { it.members["selectedCandidatePairId"] as? String }.toSet()
        val transport = transports.singleOrNull { it.members["selectedCandidatePairId"] == selected.singleOrNull() }
        var status = if (ice in setOf("connected", "completed") && selected.size != 1) "unsupported" else "not_selected"
        val pair = if (selected.size == 1 && ice in setOf("connected", "completed")) {
            runCatching {
                selectedPair(resource, epoch, stats.getValue(selected.single()), stats)
            }.getOrNull().also { status = if (it != null) "selected" else "unavailable" }
        } else null
        val availability = JSONObject().put("selected_pair", pair != null)
            .put("relay_protocol", pair != null && pair.optString("relay_protocol") != "unknown")
            .put("relay_socket", false)
            .put("pair_bytes", pair != null && !pair.isNull("bytes_sent") && !pair.isNull("bytes_received"))
            .put("rtt", pair != null && !pair.isNull("rtt_ms"))
        val dtls = (transport?.members?.get("dtlsState") as? String)?.lowercase()
            ?.takeIf { it in setOf("new", "connecting", "connected", "closed", "failed") } ?: "unknown"
        return JSONObject().put("v", 1).put("resource", resource).put("adapter_epoch", epoch)
            .put("sample_sequence", sequence).put("sampled_at_ms", sampledAt)
            .put("status", status).put("ice_state", ice).put("dtls_state", dtls).put("channel_state", channel)
            .put("pair", pair ?: JSONObject.NULL).put("application", application).put("availability", availability)
            .also { require(it.toString().toByteArray(Charsets.UTF_8).size <= 16 * 1024) }
    }

    private fun selectedPair(resource: String, epoch: String, pair: RTCStats, stats: Map<String, RTCStats>): JSONObject {
        require(pair.type == "candidate-pair" && pair.members["state"] == "succeeded")
        val localStats = stats.getValue(pair.members["localCandidateId"] as String)
        val remoteStats = stats.getValue(pair.members["remoteCandidateId"] as String)
        require(localStats.type == "local-candidate" && remoteStats.type == "remote-candidate")
        val local = candidate(localStats)
        val remote = candidate(remoteStats)
        // relayProtocol is the actual selected candidate statistic. A URL,
        // configured policy or candidate.protocol cannot substitute for it.
        val relay = if (local.getString("type") != "relay") "not_applicable" else {
            (localStats.members["relayProtocol"] as? String)?.lowercase()
                ?.takeIf { it in setOf("udp", "tcp", "tls") } ?: "unknown"
        }
        val material = "[${JSONObject.quote(epoch)},${JSONObject.quote(resource)},${canonical(local)},${canonical(remote)}]"
        val token = MessageDigest.getInstance("SHA-256").digest(material.toByteArray(Charsets.US_ASCII))
            .take(16).joinToString("") { "%02x".format(it.toInt() and 255) }
        val rtt = (pair.members["currentRoundTripTime"] as? Number)?.toDouble()?.times(1000)
            ?.takeIf { it.isFinite() && it in 0.0..3600000.0 }
        return JSONObject().put("token", token).put("local", local).put("remote", remote)
            .put("nominated", pair.members["nominated"] as? Boolean ?: JSONObject.NULL)
            .put("relay_protocol", relay)
            // Native RTCStats does not expose the actual client-to-TURN socket
            // endpoints. Relayed ICE candidate endpoints are NOT that socket.
            .put("relay_socket", JSONObject.NULL)
            .put("bytes_sent", counter(pair.members["bytesSent"]) ?: JSONObject.NULL)
            .put("bytes_received", counter(pair.members["bytesReceived"]) ?: JSONObject.NULL)
            .put("rtt_ms", rtt ?: JSONObject.NULL)
    }

    private fun counter(value: Any?): Long? =
        (value as? Number)?.toString()?.toLongOrNull()?.takeIf { it in 0..MAX_INTEGER }

    private fun candidate(stat: RTCStats): JSONObject {
        val address = (stat.members["address"] ?: stat.members["ip"]) as String
        // Permit only literal IPs; getByName must never trigger DNS here.
        require(address.matches(Regex("[0-9.]+")) || (':' in address && address.matches(Regex("[0-9A-Fa-f:.%_-]+"))))
        InetAddress.getByName(address)
        val port = counter(stat.members["port"])?.takeIf { it in 1..65535 } ?: error("invalid_port")
        val kind = stat.members["candidateType"] as String
        val protocol = (stat.members["protocol"] as String).lowercase()
        require(kind in setOf("host", "srflx", "prflx", "relay") && protocol in setOf("udp", "tcp"))
        return JSONObject().put("address", address).put("port", port).put("type", kind).put("protocol", protocol)
    }

    private fun canonical(candidate: JSONObject): String =
        "{\"address\":${JSONObject.quote(candidate.getString("address"))},\"port\":${candidate.getLong("port")}," +
        "\"protocol\":${JSONObject.quote(candidate.getString("protocol"))},\"type\":${JSONObject.quote(candidate.getString("type"))}}"
}
