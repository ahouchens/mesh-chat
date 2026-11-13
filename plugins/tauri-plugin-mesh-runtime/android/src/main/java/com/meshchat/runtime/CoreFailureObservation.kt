package com.meshchat.runtime

import android.content.Context
import org.json.JSONObject

/** Host-private reflective qualification entry. This scope cannot supply a Core caller, permission or grant. */
internal object CoreFailureObservation {
    @JvmStatic fun typedCommand(context: Context, raw: String, qualificationBinding: String): String {
        val scope = CoreCommandObservation(qualificationBinding)
        if (!CoreObservationContext.enter(scope)) return CoreApiBridge.typedCommand(context, raw)
        try {
            val original = CoreApiBridge.typedCommand(context, raw)
            return try {
                val selected = scope.finish()
                if (selected == null || !scope.stillCurrent()) original else {
                    val privateReply = JSONObject(original)
                    if (privateReply.opt("ok") != false || privateReply.optJSONObject("error")?.opt("code") != "internal") original
                    else {
                        val encoded = privateReply.put("core_failure_observation", selected.json()).toString()
                        if (scope.stillCurrent()) encoded else original
                    }
                }
            } catch (_: Exception) { original }
        } finally { CoreObservationContext.leave(scope) }
    }
}
