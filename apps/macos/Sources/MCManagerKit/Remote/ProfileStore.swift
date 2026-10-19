import Foundation
import Security

public protocol SecretStoring: Sendable {
    func read(_ account: String) -> String?
    func write(_ account: String, value: String) -> Bool
    func delete(_ account: String)
}

public final class MemorySecretStore: SecretStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: String] = [:]

    public init() {}

    public func read(_ account: String) -> String? {
        lock.lock()
        defer { lock.unlock() }
        return values[account]
    }

    public func write(_ account: String, value: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        values[account] = value
        return true
    }

    public func delete(_ account: String) {
        lock.lock()
        defer { lock.unlock() }
        values[account] = nil
    }
}

public struct KeychainSecretStore: SecretStoring {
    public static let service = "io.github.scirr.mcmanager.remote"

    public init() {}

    private func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: account,
        ]
    }

    public func read(_ account: String) -> String? {
        var search = query(account)
        search[kSecReturnData as String] = true
        search[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(search as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    public func write(_ account: String, value: String) -> Bool {
        delete(account)
        var attributes = query(account)
        attributes[kSecValueData as String] = Data(value.utf8)
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess
    }

    public func delete(_ account: String) {
        SecItemDelete(query(account) as CFDictionary)
    }
}

public final class ProfileStore: @unchecked Sendable {
    private let fileURL: URL
    private let secrets: SecretStoring

    public init(fileURL: URL, secrets: SecretStoring) {
        self.fileURL = fileURL
        self.secrets = secrets
    }

    public static func defaultFileURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory() + "/Library/Application Support")
        return base.appendingPathComponent("MCManager", isDirectory: true).appendingPathComponent("remotes.json")
    }

    public func load() -> [RemoteProfile] {
        guard let data = try? Data(contentsOf: fileURL),
              let stored = try? JSONDecoder().decode([RemoteProfile].self, from: data) else { return [] }
        return stored.map { profile in
            var full = profile
            full.token = secrets.read(profile.name) ?? ""
            return full
        }
    }

    @discardableResult
    public func save(_ profiles: [RemoteProfile]) -> Bool {
        do {
            let data = try JSONEncoder().encode(profiles)
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: fileURL, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
            return true
        } catch {
            return false
        }
    }

    @discardableResult
    public func add(_ profile: RemoteProfile) -> Bool {
        guard secrets.write(profile.name, value: profile.token) else { return false }
        var all = load().filter { $0.name != profile.name }
        all.append(profile)
        return save(all)
    }

    public func remove(_ name: String) {
        secrets.delete(name)
        save(load().filter { $0.name != name })
    }
}
