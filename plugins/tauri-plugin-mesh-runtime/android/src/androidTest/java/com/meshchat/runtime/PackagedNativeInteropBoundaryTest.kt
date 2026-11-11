package com.meshchat.runtime

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Bundle
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.security.MessageDigest

/** Explicit CI instrumentation only. No exported product service or JSON grant. */
@RunWith(AndroidJUnit4::class)
class PackagedNativeInteropBoundaryTest {
    @Test(timeout = 3_600_000)
    fun packagedNativePeerController() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val nonce = InstrumentationRegistry.getArguments().getString("mesh_interop_nonce") ?: error("Missing controller admission")
        check(nonce.matches(Regex("[a-f0-9]{64}")))
        BootstrapClient.configure(context)
        NativeWebRtcBridge.attach(context)
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        val python = Python.getInstance()
        val qualification = python.getModule("mesh_chat.core_api.qualification_host")
        val mobile = python.getModule("mesh_chat.mobile_bridge")
        var directory: File? = null
        var initialized = false
        var finished = false
        var authenticated = false
        var qualificationBinding: String? = null
        var bindingObserved = false
        var pendingNetworkBinding: String? = null
        val parent = context.filesDir.resolve("native-interop").canonicalFile
        check(parent.mkdirs() || parent.isDirectory)
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 90_000
            instrumentation.sendStatus(0, Bundle().apply { putString("mesh_interop_port", server.localPort.toString()) })
            try {
                server.accept().use { socket ->
                    socket.soTimeout = 120_000
                    val input = DataInputStream(socket.getInputStream())
                    val output = DataOutputStream(socket.getOutputStream())
                    while (!finished) {
                        val size = input.readInt()
                        check(size in 2..4 * 1024 * 1024)
                        val bytes = ByteArray(size)
                        input.readFully(bytes)
                        val frame = JSONObject(String(bytes, Charsets.UTF_8))
                        check(frame.keys().asSequence().toSet() == setOf("id", "action", "payload"))
                        val id = frame.getString("id")
                        check(id.matches(Regex("qualification:[0-9]{1,8}")))
                        val action = frame.getString("action")
                        val payload = frame.getJSONObject("payload")
                        val diagnosticRequest = action == "inspect" && payload.opt("command") == "qualification.network_diagnostic"
                        if (!diagnosticRequest) pendingNetworkBinding = null
                        var reply: JSONObject
                        try {
                            if (!authenticated) {
                                check(action == "authenticate" && payload.keys().asSequence().toSet() == setOf("nonce"))
                                check(MessageDigest.isEqual(nonce.toByteArray(), payload.getString("nonce").toByteArray()))
                                authenticated = true
                                reply = JSONObject().put("ok", true).put("result", JSONObject().put("authenticated", true))
                            } else when (action) {
                                "initialize" -> {
                                    qualificationBinding = null
                                    bindingObserved = false
                                    check(!initialized && payload.keys().asSequence().toSet() == setOf("directory_id", "vault_key"))
                                    val leaf = payload.getString("directory_id")
                                    check(leaf.matches(Regex("[a-f0-9]{32}")))
                                    check(Base64.decode(payload.getString("vault_key"), Base64.NO_WRAP).size == 32)
                                    directory = parent.resolve("mesh-qualification-$leaf").canonicalFile
                                    check(directory!!.parentFile == parent)
                                    val request = JSONObject().put("profile_dir", directory!!.absolutePath)
                                        .put("vault_key", payload.getString("vault_key")).put("display_name", "Mesh qualification")
                                        .put("platform", "android")
                                    reply = JSONObject(qualification.callAttr("android_initialize", request.toString()).toString())
                                    initialized = reply.optBoolean("ok")
                                }
                                "core" -> {
                                    check(initialized && payload.keys().asSequence().toSet() == setOf("operation", "params", "idempotency_key"))
                                    val request = JSONObject().put("action", "request").put("payload", JSONObject()
                                        .put("operation", payload.getString("operation")).put("params", payload.getJSONObject("params"))
                                        .put("idempotencyKey", payload.get("idempotency_key")))
                                    val binding = qualificationBinding
                                    val observer = if (binding == null) null else try {
                                        Class.forName("com.meshchat.runtime.CoreFailureObservation")
                                            .getDeclaredMethod("typedCommand", android.content.Context::class.java,
                                                String::class.java, String::class.java).apply { isAccessible = true }
                                    } catch (_: Exception) { null }
                                    reply = JSONObject(if (observer == null) CoreApiBridge.typedCommand(context, request.toString())
                                        else (observer.invoke(null, context, request.toString(), binding)
                                            ?: error("Observation entry returned no reply")).toString())
                                    val selected = reply.optJSONObject("core_failure_observation")
                                    val eligible = reply.opt("ok") == false &&
                                        reply.optJSONObject("error")?.opt("code") == "internal" &&
                                        selected?.length() == 5 && selected.opt("operation") == "ice_servers" &&
                                        selected.opt("stage") == "broker_open" &&
                                        selected.opt("category") == "network_unavailable" &&
                                        selected.opt("cause") == "name_resolution"
                                    pendingNetworkBinding = binding.takeIf { eligible }
                                }
                                "inspect" -> {
                                    check(initialized && payload.keys().asSequence().toSet() == setOf("command", "payload"))
                                    if (diagnosticRequest) {
                                        val expected = pendingNetworkBinding
                                        pendingNetworkBinding = null
                                        val diagnosticPayload = payload.getJSONObject("payload")
                                        check(expected != null && expected == qualificationBinding &&
                                            diagnosticPayload.keys().asSequence().toSet() == setOf("qualification_binding") &&
                                            diagnosticPayload.getString("qualification_binding") == expected)
                                        reply = JSONObject().put("ok", true).put("result", networkDiagnostic(context, python, expected))
                                    } else {
                                        reply = JSONObject(qualification.callAttr("android_control", payload.toString()).toString())
                                    }
                                    if (!diagnosticRequest && payload.opt("command") == "qualification.inventory" && reply.opt("ok") == true) {
                                        val result = reply.optJSONObject("result")
                                        val service = result?.opt("service_incarnation") as? String
                                        val profile = result?.opt("profile_incarnation") as? String
                                        val candidate = if (service?.matches(Regex("[a-f0-9]{32}")) == true &&
                                            profile?.matches(Regex("[a-f0-9]{32}")) == true) service + profile else null
                                        if (!bindingObserved && payload.getJSONObject("payload").length() == 0) {
                                            bindingObserved = true
                                            val counts = result?.optJSONObject("host_accounting")
                                            val empty = result?.optJSONArray("resources")?.length() == 0 && counts?.opt("complete") == true &&
                                                listOf("reserved_count", "creating_count", "allocated_count", "active_count", "retiring_count")
                                                    .all { counts?.opt(it) == 0 }
                                            qualificationBinding = candidate.takeIf { empty }
                                        } else if (candidate != qualificationBinding) qualificationBinding = null
                                    }
                                }
                                "finish" -> {
                                    qualificationBinding = null
                                    check(initialized && payload.keys().asSequence().toSet() == setOf("delete_profile"))
                                    val closed = JSONObject(mobile.callAttr("shutdown").toString())
                                    check(closed.getBoolean("ok"))
                                    initialized = false
                                    NativeWebRtcBridge.closeAll()
                                    val host = Class.forName("com.meshchat.runtime.NativeWebRtcHost")
                                    val reservationsField = host.getDeclaredField("reservations").apply { isAccessible = true }
                                    val reservations = reservationsField.get(null)
                                    val ids = reservations.javaClass.getMethod("ids")
                                    val deadline = System.nanoTime() + 15_000_000_000L
                                    var retired = false
                                    while (System.nanoTime() < deadline) {
                                        // Inspect actual retained ownership; shutdown may defer close.
                                        mobile.callAttr("shutdown")
                                        val storeRetired = python.builtins.callAttr("eval",
                                            "_service is None and _retiring_service is None and _retiring_channel is None",
                                            mobile.get("__dict__")).toString() == "True"
                                        val resourcesRetired = (ids.invoke(reservations) as List<*>).isEmpty()
                                        if (storeRetired && resourcesRetired) { retired = true; break }
                                        Thread.sleep(25)
                                    }
                                    check(retired)
                                    if (payload.getBoolean("delete_profile")) {
                                        check(directory!!.parentFile == parent)
                                        check(directory!!.deleteRecursively())
                                    }
                                    finished = true
                                    reply = JSONObject().put("ok", true).put("result", JSONObject().put("closed", true)
                                        .put("resources_retired", true).put("store_retired", true))
                                }
                                else -> error("Unsupported controller action")
                            }
                        } catch (_: Throwable) {
                            // Raw exceptions may contain signed signaling or caller payloads.
                            reply = JSONObject().put("ok", false).put("error", JSONObject().put("code", "qualification_host_error"))
                        }
                        reply.put("id", id)
                        val encoded = reply.toString().toByteArray(Charsets.UTF_8)
                        check(encoded.size in 2..4 * 1024 * 1024)
                        output.writeInt(encoded.size)
                        output.write(encoded)
                        output.flush()
                        if (!authenticated) error("Controller authentication failed")
                    }
                }
            } finally {
                if (initialized) mobile.callAttr("shutdown")
                NativeWebRtcBridge.closeAll()
            }
        }
        check(finished)
    }

    private fun networkDiagnostic(context: Context, python: Python, binding: String): JSONObject {
        check(binding.matches(Regex("[a-f0-9]{64}")))
        val module = python.getModule("types").callAttr("ModuleType", "mesh_qualification_network_diagnostic")
        python.builtins.callAttr("exec", NETWORK_DIAGNOSTIC, module.get("__dict__"))
        check(module.callAttr("current", binding).toString() == "True")
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = manager.activeNetwork
        val capabilities = network?.let { manager.getNetworkCapabilities(it) }
        val links = network?.let { manager.getLinkProperties(it) }
        val proxy = JSONObject(module.callAttr("connect_target", binding).toString())
        check(proxy.keys().asSequence().toSet() == setOf("connect_target"))
        val target = proxy.getString("connect_target")
        check(target in setOf("broker", "proxy", "unknown"))
        val result = JSONObject().put("v", 1).put("scope", "post_failure_app_process")
            .put("internet_permission", context.checkSelfPermission(Manifest.permission.INTERNET) == PackageManager.PERMISSION_GRANTED)
            .put("active_network", network != null)
            .put("internet_capability", capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true)
            .put("validated_network", capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true)
            .put("dns_servers_present", links?.dnsServers?.isNotEmpty() == true)
            .put("process_bound_network", manager.boundNetworkForProcess != null)
            .put("connect_target", target)
        check(module.callAttr("current", binding).toString() == "True")
        return result
    }

    companion object {
        private val NETWORK_DIAGNOSTIC = """
            import json
            from types import FunctionType
            import urllib.request
            from mesh_chat import mobile_bridge
            from mesh_chat.core_api import qualification_host

            def current(binding):
                try:
                    publication = qualification_host._android_publication
                    return (type(binding) is str and publication is not None and
                            publication.binding == binding and publication.current())
                except Exception:
                    return False

            def standard_route_builder():
                try:
                    module = urllib.request
                    opener = module.urlopen
                    builder = module.build_opener
                    proxy = module.ProxyHandler
                    source = opener.__code__.co_filename
                    return (type(opener) is FunctionType and opener.__module__ == module.__name__ and
                            opener.__qualname__ == 'urlopen' and
                            type(builder) is FunctionType and builder.__module__ == module.__name__ and
                            builder.__qualname__ == 'build_opener' and builder.__code__.co_filename == source and
                            type(proxy) is type and proxy.__module__ == module.__name__ and
                            proxy.__qualname__ == 'ProxyHandler' and
                            proxy.__init__.__code__.co_filename == source and
                            proxy.proxy_open.__code__.co_filename == source)
                except Exception:
                    return False

            def connect_target(binding):
                try:
                    if not current(binding):
                        return json.dumps({'connect_target': 'unknown'})
                    service = mobile_bridge._service
                    broker = service.call_settings().get('turn_broker_url') if service is not None else None
                    if type(broker) is not str:
                        return json.dumps({'connect_target': 'unknown'})
                    request = urllib.request.Request(broker)
                    if request.type != 'https' or not request.host:
                        return json.dumps({'connect_target': 'unknown'})
                    if (not standard_route_builder() or
                            urllib.request.getproxies is not urllib.request.getproxies_environment or
                            urllib.request.proxy_bypass is not urllib.request.proxy_bypass_environment):
                        return json.dumps({'connect_target': 'unknown'})
                    # urlopen(context=...) builds a fresh opener with ProxyHandler(getproxies()).
                    proxies = urllib.request.getproxies_environment()
                    if type(proxies) is not dict or any(type(kind) is not str for kind in proxies):
                        return json.dumps({'connect_target': 'unknown'})
                    choices = [value for kind, value in proxies.items() if kind.lower() == 'https']
                    if len(choices) > 1:
                        target = 'unknown'
                    elif not choices or urllib.request.proxy_bypass_environment(request.host, proxies):
                        target = 'broker'
                    elif type(choices[-1]) is str and choices[-1]:
                        target = 'proxy'
                    else:
                        target = 'unknown'
                    if not current(binding):
                        target = 'unknown'
                    return json.dumps({'connect_target': target})
                except Exception:
                    return json.dumps({'connect_target': 'unknown'})
        """.trimIndent()
    }
}
