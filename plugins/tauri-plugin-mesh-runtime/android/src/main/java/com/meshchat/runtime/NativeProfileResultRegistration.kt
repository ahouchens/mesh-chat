package com.meshchat.runtime

import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.contract.ActivityResultContract
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** One private result registration per confirmation; never Tauri's shared callback. */
internal class NativeProfileResultRegistration<I, O>(
    registry: ActivityResultRegistry,
    contract: ActivityResultContract<I, O>,
    receive: (O) -> Unit,
) {
    private val active = AtomicBoolean(true)
    private val launcher = AtomicReference<ActivityResultLauncher<I>?>(null)

    init {
        val registered = registry.register("mesh-profile-auth-${UUID.randomUUID()}", contract) { result ->
            if (active.compareAndSet(true, false)) {
                launcher.get()?.unregister()
                receive(result)
            }
        }
        launcher.set(registered)
        if (!active.get()) registered.unregister()
    }

    fun launch(input: I) {
        check(active.get())
        checkNotNull(launcher.get()).launch(input)
    }

    fun cancel() {
        active.set(false)
        launcher.get()?.unregister()
    }
}
