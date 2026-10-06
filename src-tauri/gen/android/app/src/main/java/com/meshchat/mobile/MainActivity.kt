package com.meshchat.mobile

import android.os.Build
import android.os.Bundle
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
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
}
