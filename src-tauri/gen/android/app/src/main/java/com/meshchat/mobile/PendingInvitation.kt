package com.meshchat.mobile

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import org.json.JSONObject

internal object PendingInvitation {
  const val PREFERENCES = "mesh-chat-launch-v1"
  const val PENDING_KEY = "pending-invitation"
  private const val MAX_STANDARD_BYTES = 32 * 1024
  private const val MAX_DEVICE_LINK_BYTES = 700 * 1024
  private const val MAX_DOCUMENT_BYTES = 16 * 1024

  private val token = Regex("^[A-Za-z0-9_-]+$")

  fun validate(raw: String): String? {
    val value = raw.trim()
    if (value.isEmpty() || value.indexOf('\u0000') >= 0) return null
    val compact = value.filterNot(Char::isWhitespace)
    val lower = compact.lowercase()
    if (lower.startsWith("meshchat://")) {
      // java.net.URI keeps this validator runnable in local JVM tests; Android's
      // Uri implementation is only needed below when opening a content URI.
      val uri = runCatching { java.net.URI(compact) }.getOrNull() ?: return null
      val kind = uri.host ?: return null
      val maximum = if (kind == "workspace-device") MAX_DEVICE_LINK_BYTES else MAX_STANDARD_BYTES
      val path = uri.rawPath ?: return null
      val segment = path.removePrefix("/")
      if (
        uri.scheme != "meshchat" ||
        kind !in setOf("invite", "workspace", "workspace-device") ||
        uri.userInfo != null || uri.port != -1 || uri.rawQuery != null || uri.rawFragment != null ||
        path != "/$segment" || segment.contains('/') || !token.matches(segment) ||
        compact.toByteArray(StandardCharsets.UTF_8).size > maximum
      ) return null
      return compact
    }

    val maximum = if (lower.startsWith("meshworkspacedevice1:")) {
      MAX_DEVICE_LINK_BYTES
    } else {
      MAX_STANDARD_BYTES
    }
    if (value.toByteArray(StandardCharsets.UTF_8).size > maximum) return null
    val prefix = when {
      lower.startsWith("meshchat1:") -> "meshchat1:"
      lower.startsWith("meshworkspace1:") -> "meshworkspace1:"
      lower.startsWith("meshworkspacedevice1:") -> "meshworkspacedevice1:"
      else -> null
    }
    if (prefix != null) {
      return if (token.matches(compact.substring(prefix.length))) value else null
    }

    // Personal .meshchat files use one exact signed JSON shape. Cryptographic,
    // expiry, key-size, and destination validation remain authoritative in the
    // Python service, but unrelated JSON never crosses into the renderer.
    if (value.toByteArray(StandardCharsets.UTF_8).size > MAX_DOCUMENT_BYTES) return null
    val document = runCatching { JSONObject(value) }.getOrNull() ?: return null
    val expected = setOf(
      "v",
      "label",
      "public_identity",
      "destination",
      "created_at",
      "expires_at",
      "hints",
      "signature",
    )
    val fields = document.keys().asSequence().toSet()
    if (
      fields == expected &&
      (document.opt("v") == 1 || document.opt("v") == 1L) &&
      listOf("label", "public_identity", "destination", "signature")
        .all { document.opt(it) is String && (document.opt(it) as String).isNotEmpty() } &&
      (document.opt("created_at") is Int || document.opt("created_at") is Long) &&
      (document.opt("expires_at") is Int || document.opt("expires_at") is Long) &&
      document.optJSONArray("hints") != null
    ) return value
    return null
  }

  private fun isMeshChatFile(activity: Activity, uri: Uri): Boolean {
    if (uri.lastPathSegment.orEmpty().lowercase().endsWith(".meshchat")) return true
    return runCatching {
      activity.contentResolver.query(
        uri,
        arrayOf(OpenableColumns.DISPLAY_NAME),
        null,
        null,
        null,
      )?.use { cursor ->
        cursor.moveToFirst() &&
          cursor.getString(cursor.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME))
            .lowercase()
            .endsWith(".meshchat")
      } == true
    }.getOrDefault(false)
  }

  private fun readBounded(activity: Activity, uri: Uri): String? {
    if (uri.scheme != "content" || !isMeshChatFile(activity, uri)) return null
    val bytes = activity.contentResolver.openInputStream(uri)?.use { stream ->
      val output = ByteArrayOutputStream()
      val buffer = ByteArray(8192)
      while (output.size() <= MAX_DOCUMENT_BYTES) {
        val count = stream.read(buffer)
        if (count < 0) break
        output.write(buffer, 0, count)
      }
      if (output.size() > MAX_DOCUMENT_BYTES) return@use null
      output.toByteArray()
    } ?: return null
    return runCatching {
      StandardCharsets.UTF_8.newDecoder()
        .onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT)
        .decode(ByteBuffer.wrap(bytes))
        .toString()
    }.getOrNull()
  }

  fun capture(activity: Activity, intent: Intent?): Boolean {
    if (intent?.action != Intent.ACTION_VIEW) return false
    val uri = intent.data ?: return true
    val candidate = if (uri.scheme == "meshchat") uri.toString() else readBounded(activity, uri)
    val invitation = candidate?.let(::validate) ?: return true
    activity.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
      .edit()
      .putString(PENDING_KEY, invitation)
      .commit()
    return true
  }

  fun isNotification(intent: Intent?): Boolean {
    val uri = intent?.data ?: return false
    return intent.action == Intent.ACTION_VIEW &&
      uri.scheme == "meshchat" && uri.host == "notification" &&
      uri.pathSegments.size == 1 && uri.pathSegments[0].matches(Regex("^[0-9a-f]{64}$"))
  }
}
