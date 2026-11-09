// The optimized smoke APK compiles these tests in a separate Kotlin module.
// Exercise its actual production registration without exposing it as host API.
@file:Suppress("INVISIBLE_REFERENCE", "INVISIBLE_MEMBER")

package com.meshchat.runtime

import android.app.Activity
import android.content.Context
import android.content.Intent
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.contract.ActivityResultContract
import androidx.core.app.ActivityOptionsCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Actual AndroidX registry routing; does not simulate a successful OS credential UI. */
@RunWith(AndroidJUnit4::class)
class NativeProfileResultRegistrationTest {
    private class RecordingRegistry : ActivityResultRegistry() {
        val requests = mutableListOf<Int>()
        override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>,
                                   input: I, options: ActivityOptionsCompat?) {
            requests.add(requestCode)
        }
    }

    private val contract = object : ActivityResultContract<Unit, Int>() {
        override fun createIntent(context: Context, input: Unit): Intent = Intent()
        override fun parseResult(resultCode: Int, intent: Intent?): Int = resultCode
    }

    private fun onMain(test: () -> Unit) =
        InstrumentationRegistry.getInstrumentation().runOnMainSync(test)

    @Test fun overlappingNonAuthSuccessCannotVerifyTheCurrentConfirmation() = onMain {
        val registry = RecordingRegistry()
        val gate = NativeProfileAuthorization()
        val challenge = "a".repeat(32)
        assertTrue(gate.begin(challenge))
        var unrelated = 0
        val picker = registry.register("unrelated-picker", contract) { unrelated++ }
        picker.launch(Unit)
        val pickerCode = registry.requests.last()
        val auth = NativeProfileResultRegistration(registry, contract) { result ->
            if (result == Activity.RESULT_OK) assertTrue(gate.verified(challenge))
        }
        auth.launch(Unit)
        val authCode = registry.requests.last()
        assertNotEquals(pickerCode, authCode)
        assertTrue(registry.dispatchResult(pickerCode, Activity.RESULT_OK))
        assertEquals(1, unrelated)
        assertFalse(gate.consume(challenge))
        assertTrue(registry.dispatchResult(authCode, Activity.RESULT_OK))
        assertTrue(gate.consume(challenge))
        assertFalse(gate.consume(challenge))
        auth.cancel()
        picker.unregister()
    }

    @Test fun cancelledActivityResultCannotAuthorizeAReplacementChallenge() = onMain {
        val registry = RecordingRegistry()
        val gate = NativeProfileAuthorization()
        val old = "a".repeat(32)
        val fresh = "b".repeat(32)
        var completions = 0
        assertTrue(gate.begin(old))
        val oldAuth = NativeProfileResultRegistration(registry, contract) { result ->
            completions++
            if (result == Activity.RESULT_OK) gate.verified(old)
        }
        oldAuth.launch(Unit)
        val oldCode = registry.requests.last()
        oldAuth.cancel() // Same registration revocation used by destruction and timeout.
        gate.cancelAll()
        assertTrue(gate.begin(fresh))
        val freshAuth = NativeProfileResultRegistration(registry, contract) { result ->
            completions++
            if (result == Activity.RESULT_OK) assertTrue(gate.verified(fresh))
        }
        freshAuth.launch(Unit)
        val freshCode = registry.requests.last()
        registry.dispatchResult(oldCode, Activity.RESULT_OK)
        assertEquals(0, completions)
        assertFalse(gate.consume(fresh))
        registry.dispatchResult(freshCode, Activity.RESULT_OK)
        assertEquals(1, completions)
        assertTrue(gate.consume(fresh))
        freshAuth.cancel()
    }

    @Test fun cancelledCredentialUiCannotSupplyProof() = onMain {
        val registry = RecordingRegistry()
        val gate = NativeProfileAuthorization()
        val challenge = "a".repeat(32)
        assertTrue(gate.begin(challenge))
        val auth = NativeProfileResultRegistration(registry, contract) { result ->
            if (result == Activity.RESULT_OK) gate.verified(challenge) else gate.cancel(challenge)
        }
        auth.launch(Unit)
        registry.dispatchResult(registry.requests.last(), Activity.RESULT_CANCELED)
        assertFalse(gate.consume(challenge))
        auth.cancel()
    }
}
