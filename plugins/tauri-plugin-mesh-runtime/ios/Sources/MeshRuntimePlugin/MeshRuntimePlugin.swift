import Foundation
import PythonBridge
import Security
import SwiftRs
import Tauri
import UIKit
import UserNotifications

final class InitializeArgs: Decodable {
    let displayName: String?
}

final class ExternalLinkArgs: Decodable { let url: String }

final class CommandArgs: Decodable {
    let command: String
    let payload: [String: JSONValue]
}

enum JSONValue: Decodable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try container.decode([JSONValue].self)) }
    }

    var foundation: Any {
        switch self {
        case .string(let value): value
        case .number(let value): value
        case .bool(let value): value
        case .object(let value): value.mapValues(\.foundation)
        case .array(let value): value.map(\.foundation)
        case .null: NSNull()
        }
    }
}

final class MeshRuntimePlugin: Plugin, UNUserNotificationCenterDelegate {
    private let queue = DispatchQueue(label: "com.meshchat.runtime", qos: .userInitiated)
    private var started = false
    private var runtimeInitialized = false
    private var notificationTimer: DispatchSourceTimer?
    private var lifecycleObserversInstalled = false

    private func vaultKey() throws -> Data {
        let account = "vault-key-v1"
        let service = "com.meshchat.mobile"
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecSuccess, let data = result as? Data, data.count == 32 { return data }
        guard status == errSecItemNotFound else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }

        var bytes = Data(count: 32)
        let randomStatus = bytes.withUnsafeMutableBytes { (buffer: UnsafeMutableRawBufferPointer) in
            SecRandomCopyBytes(kSecRandomDefault, 32, buffer.baseAddress!)
        }
        guard randomStatus == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(randomStatus)) }
        var add = query
        add.removeValue(forKey: kSecReturnData as String)
        add.removeValue(forKey: kSecMatchLimit as String)
        add[kSecValueData as String] = bytes
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let addStatus = SecItemAdd(add as CFDictionary, nil)
        guard addStatus == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(addStatus)) }
        return bytes
    }

    private func profileDirectory() throws -> URL {
        let support = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = support.appendingPathComponent("profile-v1", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: directory.path)
        return directory
    }

    private func ensurePython() throws {
        if started { return }
        guard let resources = Bundle.main.resourceURL,
              mesh_python_start(resources.path) == 0 else {
            throw NSError(domain: "MeshRuntime", code: 1)
        }
        started = true
    }

    private func call(_ function: String, request: [String: Any]? = nil) throws -> String {
        try ensurePython()
        let requestData = try request.map { try JSONSerialization.data(withJSONObject: $0) }
        let requestString = requestData.flatMap { String(data: $0, encoding: .utf8) }
        let pointer = function.withCString { functionPointer in
            if let requestString {
                return requestString.withCString { requestPointer in
                    mesh_python_invoke(functionPointer, requestPointer)
                }
            }
            return mesh_python_invoke(functionPointer, nil)
        }
        guard let pointer else { throw NSError(domain: "MeshRuntime", code: 2) }
        defer { mesh_python_free(pointer) }
        return String(cString: pointer)
    }

    private func nativeCommand(_ command: String, payload: [String: Any] = [:]) throws -> [String: Any] {
        let raw = try call("command", request: ["command": command, "payload": payload])
        guard let data = raw.data(using: .utf8),
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "MeshRuntime", code: 3)
        }
        return value
    }

    private func success(_ result: [String: Any]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: ["ok": true, "result": result])
        guard let value = String(data: data, encoding: .utf8) else {
            throw NSError(domain: "MeshRuntime", code: 4)
        }
        return value
    }

    private func permissionState(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .authorized, .provisional, .ephemeral: return "allowed"
        case .notDetermined: return "not_requested"
        case .denied: return "settings_required"
        @unknown default: return "denied"
        }
    }

    private func capability(_ settings: UNNotificationSettings) -> [String: Any] {
        [
            "supported": true,
            "platform": "ios",
            "permission_state": permissionState(settings.authorizationStatus),
        ]
    }

    private func syncNativeState(_ completion: (() -> Void)? = nil) {
        guard runtimeInitialized else { completion?(); return }
        UNUserNotificationCenter.current().getNotificationSettings { [weak self] settings in
            guard let self else { completion?(); return }
            self.queue.async {
                _ = try? self.nativeCommand("native_notification_state", payload: self.capability(settings))
                completion?()
            }
        }
    }

    private func lifecycle(_ state: String, reason: String) {
        guard runtimeInitialized else { return }
        queue.async { [weak self] in
            guard let self else { return }
            self.syncNativeState()
            _ = try? self.nativeCommand(
                "mobile_lifecycle_transition",
                payload: ["state": state, "reason": reason]
            )
        }
    }

    @objc private func enteredBackground() {
        lifecycle("background", reason: "application_background")
        lifecycle("suspended", reason: "application_suspension_boundary")
    }

    @objc private func enteredForeground() {
        lifecycle("foreground", reason: "application_foreground")
    }

    private func installLifecycleObservers() {
        guard !lifecycleObserversInstalled else { return }
        lifecycleObserversInstalled = true
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(enteredBackground),
            name: UIApplication.didEnterBackgroundNotification,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(enteredForeground),
            name: UIApplication.willEnterForegroundNotification,
            object: nil
        )
    }

    private func validPlainText(_ value: String, maximum: Int) -> Bool {
        value.count <= maximum && value.unicodeScalars.allSatisfy {
            !CharacterSet.controlCharacters.contains($0) &&
            $0.properties.generalCategory != .format &&
            $0.properties.generalCategory != .surrogate
        }
    }

    private func acknowledge(_ identifier: String, outcome: String) {
        _ = try? nativeCommand(
            "acknowledge_native_notification",
            payload: ["notification_id": identifier, "outcome": outcome]
        )
    }

    private func displayNativeWork(_ item: [String: Any]) {
        let identifier = item["notification_id"] as? String
        let validIdentifier = identifier?.range(
            of: "^[0-9a-f]{64}$",
            options: .regularExpression
        ) != nil
        guard let identifier, validIdentifier,
              let group = item["grouping_key"] as? String,
              group.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil,
              let category = item["category"] as? String,
              ["mention", "thread_reply", "direct_message", "channel_message"].contains(category),
              let title = item["title"] as? String,
              let body = item["body"] as? String,
              validPlainText(title, maximum: 80),
              validPlainText(body, maximum: 160),
              let encoded = try? JSONSerialization.data(withJSONObject: item),
              encoded.count <= 1024 else {
            if let identifier, validIdentifier { acknowledge(identifier, outcome: "denied") }
            return
        }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.threadIdentifier = group
        content.categoryIdentifier = category
        content.userInfo = ["notification_id": identifier]
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request) { [weak self] error in
            self?.queue.async {
                self?.acknowledge(identifier, outcome: error == nil ? "accepted" : "retry")
            }
        }
    }

    private func drainNativeNotifications() {
        guard runtimeInitialized,
              let response = try? nativeCommand(
                "drain_native_notification_work",
                payload: ["limit": 16]
              ),
              response["ok"] as? Bool == true,
              let result = response["result"] as? [String: Any],
              let items = result["items"] as? [[String: Any]] else { return }
        for item in items.prefix(16) { displayNativeWork(item) }
    }

    private func startNotificationPump() {
        guard notificationTimer == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(750))
        timer.setEventHandler { [weak self] in self?.drainNativeNotifications() }
        timer.resume()
        notificationTimer = timer
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        defer { completionHandler() }
        guard let identifier = response.notification.request.content.userInfo["notification_id"] as? String,
              identifier.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let url = URL(string: "meshchat://notification/\(identifier)") else { return }
        DispatchQueue.main.async { UIApplication.shared.open(url) }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([])
    }

    private func resolve(_ invoke: Invoke, _ action: @escaping () throws -> String) {
        queue.async {
            do { invoke.resolve(["json": try action()]) }
            catch { invoke.reject("mobile_runtime_unavailable") }
        }
    }

    @objc func initialize(_ invoke: Invoke) throws {
        let args = try invoke.parseArgs(InitializeArgs.self)
        resolve(invoke) { [self] in
            let result = try call("initialize", request: [
                "profile_dir": try profileDirectory().path,
                "vault_key": try vaultKey().base64EncodedString(),
                "display_name": args.displayName.map { $0 as Any } ?? NSNull(),
                "platform": "ios",
            ])
            runtimeInitialized = true
            UNUserNotificationCenter.current().delegate = self
            installLifecycleObservers()
            startNotificationPump()
            syncNativeState()
            _ = try? nativeCommand(
                "mobile_lifecycle_transition",
                payload: ["state": "foreground", "reason": "runtime_initialized"]
            )
            return result
        }
    }

    @objc func command(_ invoke: Invoke) throws {
        let args = try invoke.parseArgs(CommandArgs.self)
        resolve(invoke) { [self] in
            try call("command", request: [
                "command": args.command,
                "payload": args.payload.mapValues(\.foundation),
            ])
        }
    }

    @objc func drainEvents(_ invoke: Invoke) {
        resolve(invoke) { [self] in try call("drain_events") }
    }

    @objc func notificationCapability(_ invoke: Invoke) {
        UNUserNotificationCenter.current().getNotificationSettings { [weak self] settings in
            guard let self else { invoke.reject("mobile_runtime_unavailable"); return }
            self.queue.async {
                do {
                    self.syncNativeState()
                    invoke.resolve(["json": try self.success(self.capability(settings))])
                } catch { invoke.reject("mobile_runtime_unavailable") }
            }
        }
    }

    @objc func requestNotificationPermission(_ invoke: Invoke) {
        UNUserNotificationCenter.current().getNotificationSettings { [weak self] settings in
            guard let self else { invoke.reject("mobile_runtime_unavailable"); return }
            guard settings.authorizationStatus == .notDetermined else {
                self.queue.async {
                    do { invoke.resolve(["json": try self.success(self.capability(settings))]) }
                    catch { invoke.reject("mobile_runtime_unavailable") }
                }
                return
            }
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { _, _ in
                UNUserNotificationCenter.current().getNotificationSettings { current in
                    self.queue.async {
                        do {
                            self.syncNativeState()
                            invoke.resolve(["json": try self.success(self.capability(current))])
                        } catch { invoke.reject("mobile_runtime_unavailable") }
                    }
                }
            }
        }
    }

    @objc func openNotificationSettings(_ invoke: Invoke) {
        DispatchQueue.main.async {
            guard let url = URL(string: UIApplication.openSettingsURLString) else {
                invoke.reject("mobile_runtime_unavailable")
                return
            }
            UIApplication.shared.open(url) { _ in
                self.notificationCapability(invoke)
            }
        }
    }

    @objc func openExternalLink(_ invoke: Invoke) throws {
        let args = try invoke.parseArgs(ExternalLinkArgs.self)
        guard args.url.count <= 4096,
              args.url.rangeOfCharacter(from: .controlCharacters) == nil,
              let url = URL(string: args.url), ["http", "https"].contains(url.scheme ?? ""),
              url.host != nil, url.user == nil, url.password == nil else {
            invoke.reject("invalid_url")
            return
        }
        DispatchQueue.main.async {
            UIApplication.shared.open(url) { opened in
                if opened { invoke.resolve(["json": "{\"ok\":true,\"result\":{\"opened\":true}}"] ) }
                else { invoke.reject("browser_unavailable") }
            }
        }
    }

    @objc func shutdown(_ invoke: Invoke) {
        resolve(invoke) { [self] in
            runtimeInitialized = false
            return try call("shutdown")
        }
    }
}

@_cdecl("init_plugin_mesh_runtime")
func initPlugin() -> Plugin {
    MeshRuntimePlugin()
}
