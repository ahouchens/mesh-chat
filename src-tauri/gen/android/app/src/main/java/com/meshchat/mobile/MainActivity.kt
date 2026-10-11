package com.meshchat.mobile

import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

class MainActivity : TauriActivity() {
  private fun captureLaunch(intent: Intent?) {
    if (PendingInvitation.isNotification(intent)) return
    if (PendingInvitation.capture(this, intent)) {
      // Do not let activity recreation or the deep-link plugin replay a value
      // which is now durably owned by the bounded pending slot.
      setIntent(Intent(Intent.ACTION_MAIN).setPackage(packageName))
    }
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    captureLaunch(intent)
    super.onCreate(savedInstanceState)

    // Android 15+ forces edge-to-edge for our target SDK. Some supported
    // WebViews predate reliable CSS safe-area values, so inset the root view
    // natively and pass only the remaining (for example, IME) insets through.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
      val safeTypes =
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
      ViewCompat.setOnApplyWindowInsetsListener(window.decorView) { view, windowInsets ->
        val safeInsets = windowInsets.getInsets(safeTypes)
        view.setPadding(safeInsets.left, safeInsets.top, safeInsets.right, safeInsets.bottom)
        WindowInsetsCompat.Builder(windowInsets)
          .setInsets(safeTypes, Insets.NONE)
          .build()
      }
      ViewCompat.requestApplyInsets(window.decorView)
    }
  }

  override fun onNewIntent(intent: Intent) {
    if (PendingInvitation.isNotification(intent)) {
      super.onNewIntent(intent)
      setIntent(intent)
      return
    }
    PendingInvitation.capture(this, intent)
    val sanitized = Intent(Intent.ACTION_MAIN).setPackage(packageName)
    super.onNewIntent(sanitized)
    setIntent(sanitized)
  }
}
