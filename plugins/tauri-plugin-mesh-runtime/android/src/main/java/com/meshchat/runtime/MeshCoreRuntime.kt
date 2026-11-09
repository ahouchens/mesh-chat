package com.meshchat.runtime

import android.app.Activity
import android.app.ActivityManager
import android.app.Application
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Build
import android.os.Looper
import android.os.Process
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CompletableFuture
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

class MeshCoreRuntimeException(val code: String) : IllegalStateException(code)

/** Trusted installing-app bootstrap. Public SDK requests never enter this API. */
object MeshCoreRuntime {
    enum class State { UNLOCKED, LOCKED, RETIRING }
    data class Credential(val credentialHandle: String, val expiresInMillis: Long,
                          val revision: Long, val hostGeneration: String)

    private val executor = ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS,
        ArrayBlockingQueue<Runnable>(1), { task -> Thread(task, "mesh-core-host").apply { isDaemon = true } })
    private val occupied = AtomicBoolean()
    private val installed = AtomicBoolean()
    private val epoch = AtomicLong()
    private val context = AtomicReference<Context?>(null)
    private val gate = NativeProfileAuthorization()
    private val main = Handler(Looper.getMainLooper())
    private var provider: NativeProfileProvider? = null

    private class Confirmation(val activity: ComponentActivity, val profile: String, val epoch: Long) {
        val future = CompletableFuture<Credential>()
        var challenge: String? = null
        var registration: NativeProfileResultRegistration<Intent, ActivityResult>? = null
        var observer: DefaultLifecycleObserver? = null
        var timeout: Runnable? = null
    }
    private val confirmation = AtomicReference<Confirmation?>(null)

    internal fun isInstalled(): Boolean = installed.get()

    @JvmStatic fun isMainProcess(value: Context): Boolean {
        val app = value.applicationContext
        val expected = app.applicationInfo.processName ?: return false
        if (expected == "${app.packageName}:mesh_bootstrap") return false
        val observed = if (Build.VERSION.SDK_INT >= 28) Application.getProcessName() else
            (app.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager)?.runningAppProcesses
                ?.firstOrNull { it.pid == Process.myPid() }?.processName
        return expected == observed
    }

    private fun <T> submit(operation: () -> T): CompletableFuture<T> {
        val future = CompletableFuture<T>()
        if (!occupied.compareAndSet(false, true)) {
            future.completeExceptionally(MeshCoreRuntimeException("resource_exhausted"))
            return future
        }
        try {
            executor.execute {
                val result = runCatching(operation)
                occupied.set(false)
                result.fold(future::complete) {
                    future.completeExceptionally(if (it is MeshCoreRuntimeException) it
                        else MeshCoreRuntimeException("unavailable"))
                }
            }
        } catch (_: RejectedExecutionException) {
            occupied.set(false)
            future.completeExceptionally(MeshCoreRuntimeException("unavailable"))
        }
        return future
    }

    private fun call(function: String, vararg arguments: Any): JSONObject {
        val reply = JSONObject(Python.getInstance().getModule("mesh_chat.mobile_bridge")
            .callAttr(function, *arguments).toString())
        if (!reply.optBoolean("ok")) {
            throw MeshCoreRuntimeException(reply.optJSONObject("error")?.optString("code")
                ?.takeIf { it.isNotEmpty() } ?: "unavailable")
        }
        return reply.optJSONObject("result") ?: JSONObject()
    }

    private fun state(): State = when (call("profile_runtime_context").getString("state")) {
        "unlocked" -> State.UNLOCKED
        "locked" -> State.LOCKED
        else -> State.RETIRING
    }

    @JvmStatic fun start(value: Context): CompletableFuture<State> = submit {
        val app = value.applicationContext
        if (!isMainProcess(app)) throw MeshCoreRuntimeException("forbidden")
        val previous = context.get()
        if (previous != null && previous.packageName != app.packageName) {
            throw MeshCoreRuntimeException("forbidden")
        }
        context.set(app)
        if (!Python.isStarted()) Python.start(AndroidPlatform(app))
        BootstrapClient.configure(app)
        NativeWebRtcBridge.attach(app)
        if (installed.get()) return@submit state()
        val keys = app.getSharedPreferences("mesh-core-runtime-keys", Context.MODE_PRIVATE)
        val profile = app.filesDir.resolve("mesh-core-runtime/profile-v1").canonicalFile
        val current = provider ?: NativeProfileProvider(profile.path, app.packageName,
            loadExistingKey = {
                check(!profile.resolve("mesh-chat.vault").exists() || keys.contains("profile-key")) {
                    "native_key_unavailable"
                }
                NativeProtectedKeyStore.load("mesh-core-runtime-profile-key-v1", keys, "profile-key")
            }, loadCatalogKey = {
                NativeProtectedKeyStore.load("mesh-core-runtime-catalog-key-v1", keys, "catalog-key")
            }, authorization = gate, beforeOpen = { NativeWebRtcBridge.attach(app) })
            .also { provider = it }
        try {
            call("initialize_app_owned_host", current)
            installed.set(true)
            epoch.incrementAndGet()
            State.UNLOCKED
        } catch (error: MeshCoreRuntimeException) {
            if (error.code != "locked") throw error
            installed.set(true)
            epoch.incrementAndGet()
            state()
        }
    }

    @JvmStatic fun shutdown(): CompletableFuture<Unit> = submit {
        epoch.incrementAndGet()
        main.post { confirmation.get()?.let { cancel(it, "authentication_cancelled") } }
        gate.cancelAll()
        if (Python.isStarted()) {
            call("shutdown")
            NativeWebRtcBridge.retireAll()
        }
        installed.set(false)
    }

    @JvmStatic fun confirmUnlock(activity: ComponentActivity, profile: String): CompletableFuture<Credential> {
        val pending = Confirmation(activity, profile, epoch.get())
        if (!installed.get() || profile.length !in 1..128) {
            pending.future.completeExceptionally(MeshCoreRuntimeException("unavailable"))
            return pending.future
        }
        if (!confirmation.compareAndSet(null, pending)) {
            pending.future.completeExceptionally(MeshCoreRuntimeException("resource_exhausted"))
            return pending.future
        }
        pending.future.whenComplete { _, _ ->
            if (pending.future.isCancelled) main.post { cancel(pending, "authentication_cancelled") }
        }
        submit { call("begin_profile_unlock_auth", profile).getString("challenge") }.whenComplete { challenge, error ->
            main.post {
                if (error != null) {
                    cancel(pending, (error as? MeshCoreRuntimeException)?.code ?: "unavailable")
                } else {
                    pending.challenge = challenge
                    launchConfirmation(pending)
                }
            }
        }
        return pending.future
    }

    private fun launchConfirmation(pending: Confirmation) {
        if (confirmation.get() !== pending) {
            pending.challenge?.let { challenge -> submit { call("cancel_profile_unlock_auth", challenge) } }
            return
        }
        if (pending.epoch != epoch.get() || !installed.get()) { cancel(pending, "resync_required"); return }
        val activity = pending.activity
        val keyguard = activity.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        if (activity.isDestroyed || activity.isFinishing || activity.lifecycle.currentState == Lifecycle.State.DESTROYED) {
            cancel(pending, "authentication_cancelled"); return
        }
        if (keyguard == null || !keyguard.isDeviceSecure) {
            cancel(pending, "authentication_unavailable"); return
        }
        @Suppress("DEPRECATION")
        val intent = keyguard.createConfirmDeviceCredentialIntent("Unlock profile", "Confirm your device credential.")
        val challenge = pending.challenge
        if (intent == null || challenge == null || !gate.begin(challenge)) {
            cancel(pending, "authentication_unavailable"); return
        }
        try {
            pending.observer = object : DefaultLifecycleObserver {
                override fun onDestroy(owner: LifecycleOwner) { cancel(pending, "authentication_cancelled") }
            }.also { activity.lifecycle.addObserver(it) }
            pending.registration = NativeProfileResultRegistration(activity.activityResultRegistry,
                ActivityResultContracts.StartActivityForResult()) { result -> receiveConfirmation(pending, result) }
            pending.timeout = Runnable { cancel(pending, "resync_required") }
            main.postDelayed(pending.timeout!!, 60_000)
            pending.registration!!.launch(intent)
        } catch (_: Throwable) { cancel(pending, "authentication_unavailable") }
    }

    private fun receiveConfirmation(pending: Confirmation, result: ActivityResult) {
        if (confirmation.get() !== pending) return
        if (pending.epoch != epoch.get() || !installed.get()) { cancel(pending, "resync_required"); return }
        pending.registration?.cancel()
        val challenge = pending.challenge ?: return cancel(pending, "resync_required")
        if (result.resultCode != Activity.RESULT_OK) {
            cancel(pending, "authentication_cancelled"); return
        }
        if (!gate.verified(challenge)) { cancel(pending, "resync_required"); return }
        submit { call("complete_profile_unlock_auth", challenge) }.whenComplete { value, error ->
            main.post {
                if (confirmation.get() !== pending) return@post
                if (pending.epoch != epoch.get() || !installed.get()) {
                    cancel(pending, "resync_required")
                } else if (pending.activity.isDestroyed || pending.activity.isFinishing) {
                    cancel(pending, "authentication_cancelled")
                } else if (error != null) {
                    cancel(pending, (error as? MeshCoreRuntimeException)?.code ?: "unavailable")
                } else {
                    try {
                        val credential = Credential(value.getString("credential_handle"), value.getLong("expires_in_ms"),
                            value.getLong("revision"), value.getString("host_generation"))
                        if (confirmation.compareAndSet(pending, null)) {
                            detach(pending)
                            pending.future.complete(credential)
                        }
                    } catch (_: Throwable) { cancel(pending, "unavailable") }
                }
            }
        }
    }

    private fun detach(pending: Confirmation) {
        pending.registration?.cancel()
        pending.observer?.let { pending.activity.lifecycle.removeObserver(it) }
        pending.timeout?.let(main::removeCallbacks)
        pending.challenge?.let(gate::cancel)
    }

    private fun cancel(pending: Confirmation, code: String) {
        if (!confirmation.compareAndSet(pending, null)) return
        detach(pending)
        pending.future.completeExceptionally(MeshCoreRuntimeException(code))
        pending.challenge?.let { challenge -> submit { call("cancel_profile_unlock_auth", challenge) } }
    }
}
