package com.meshchat.runtime.smoke

import android.app.Activity
import com.meshchat.runtime.BackgroundRuntime

/** CI host for the same restoration hook used by MeshRuntimePlugin. */
class BackgroundTestActivity : Activity() {
    override fun onResume() {
        super.onResume()
        BackgroundRuntime.onUiLifecycle("foreground")
        BackgroundRuntime.restoreIfEnabled(this)
    }

    override fun onStop() {
        BackgroundRuntime.onUiLifecycle("background_available")
        super.onStop()
    }
}
