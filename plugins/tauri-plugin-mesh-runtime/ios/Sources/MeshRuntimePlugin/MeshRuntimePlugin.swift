import Foundation
import PythonBridge
import Security
import SwiftRs
import Tauri
import UIKit

final class InitializeArgs: Decodable {
    let displayName: String?
}

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

final class MeshRuntimePlugin: Plugin {
    private let queue = DispatchQueue(label: "com.meshchat.runtime", qos: .userInitiated)
    private var started = false

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

    private func resolve(_ invoke: Invoke, _ action: @escaping () throws -> String) {
        queue.async {
            do { invoke.resolve(["json": try action()]) }
            catch { invoke.reject("mobile_runtime_unavailable") }
        }
    }

    @objc func initialize(_ invoke: Invoke) throws {
        let args = try invoke.parseArgs(InitializeArgs.self)
        resolve(invoke) { [self] in
            try call("initialize", request: [
                "profile_dir": try profileDirectory().path,
                "vault_key": try vaultKey().base64EncodedString(),
                "display_name": args.displayName.map { $0 as Any } ?? NSNull(),
                "platform": "ios",
            ])
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

    @objc func shutdown(_ invoke: Invoke) {
        resolve(invoke) { [self] in try call("shutdown") }
    }
}

@_cdecl("init_plugin_mesh_runtime")
func initPlugin() -> Plugin {
    MeshRuntimePlugin()
}
