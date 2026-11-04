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
