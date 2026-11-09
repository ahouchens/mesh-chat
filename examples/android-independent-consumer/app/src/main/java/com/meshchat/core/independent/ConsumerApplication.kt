package com.meshchat.core.independent

import android.app.Application
import com.meshchat.runtime.MeshCoreRuntime
import java.util.concurrent.CompletableFuture

class ConsumerApplication : Application() {
    var startup: CompletableFuture<MeshCoreRuntime.State>? = null
        private set

    override fun onCreate() {
        super.onCreate()
        if (MeshCoreRuntime.isMainProcess(this)) startup = MeshCoreRuntime.start(this)
    }
}
