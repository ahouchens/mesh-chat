package com.meshchat.runtime

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** Direct native-host lifecycle checks without Chromium or a rendered call. */
@RunWith(AndroidJUnit4::class)
class NativeWebRtcHostLifecycleTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val ice = """{"iceServers":[]}"""
    private val channels = """[{"label":"mesh-reticulum","binary":true,"ordered":true}]"""

    @Before
    fun setUp() {
        NativeWebRtcHost.initialize(context)
        NativeWebRtcHost.closeAll()
    }

    @After
    fun tearDown() {
        NativeWebRtcHost.closeAll()
    }

    private fun json(value: String) = JSONObject(value)

    private fun assertMissing(session: String) {
        val stats = json(NativeWebRtcHost.stats(session))
        assertFalse(stats.optBoolean("ok"))
        assertEquals("native_webrtc_session_missing", stats.optString("error"))
    }

    private fun offer(session: String): String {
        val created = json(NativeWebRtcHost.createOffer(session, ice, channels))
        assertTrue(created.toString(), created.optBoolean("ok"))
        return created.getString("sdp")
    }

    @Test
    fun cancellationAfterOfferRetiresTheSessionAndFreesCapacity() {
        offer("lifecycle-offer")
        NativeWebRtcHost.close("lifecycle-offer")
        assertMissing("lifecycle-offer")
        offer("lifecycle-replacement")
        NativeWebRtcHost.close("lifecycle-replacement")
        assertMissing("lifecycle-replacement")
    }


    @Test
    fun invalidFramesAndMissingChannelsFailClosed() {
        assertFalse(NativeWebRtcHost.send("missing", ByteArray(1)))
        assertFalse(NativeWebRtcHost.send("missing", ByteArray(1065)))
        assertFalse(NativeWebRtcHost.sendControl("missing", "mesh-onboarding", "x"))
        assertFalse(NativeWebRtcHost.sendControl("missing", "mesh-onboarding", "x".repeat(65_537)))
        val missing = json(NativeWebRtcHost.createOffer(
            "missing-channel", ice,
            """[{"label":"mesh-onboarding","binary":false,"ordered":true}]""",
        ))
        assertFalse(missing.optBoolean("ok"))
        assertEquals("native_webrtc_missing_data_channel", missing.optString("error"))
        NativeWebRtcHost.close("missing")
        assertMissing("missing")
    }

    @Test
    fun closeAllRetiresEveryLiveSession() {
        offer("lifecycle-all-a")
        offer("lifecycle-all-b")
        NativeWebRtcHost.closeAll()
        assertMissing("lifecycle-all-a")
        assertMissing("lifecycle-all-b")
        offer("lifecycle-all-replacement")
        NativeWebRtcHost.close("lifecycle-all-replacement")
        assertMissing("lifecycle-all-replacement")
    }

    @Test
    fun cancellationAfterAcceptRetiresBothSessions() {
        val left = offer("lifecycle-left")
        val accepted = json(NativeWebRtcHost.acceptOffer("lifecycle-right", left, ice, channels))
        assertTrue(accepted.toString(), accepted.optBoolean("ok"))
        NativeWebRtcHost.close("lifecycle-left")
        NativeWebRtcHost.close("lifecycle-right")
        assertMissing("lifecycle-left")
        assertMissing("lifecycle-right")
    }

    @Test
    fun cancellationAfterAnswerRetiresBothSessions() {
        val left = offer("lifecycle-answer-left")
        val accepted = json(NativeWebRtcHost.acceptOffer("lifecycle-answer-right", left, ice, channels))
        assertTrue(accepted.toString(), accepted.optBoolean("ok"))
        val applied = json(NativeWebRtcHost.applyAnswer("lifecycle-answer-left", accepted.getString("sdp")))
        assertTrue(applied.toString(), applied.optBoolean("ok"))
        NativeWebRtcHost.close("lifecycle-answer-left")
        NativeWebRtcHost.close("lifecycle-answer-right")
        assertMissing("lifecycle-answer-left")
        assertMissing("lifecycle-answer-right")
    }
}
