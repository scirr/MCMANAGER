import Foundation

public struct AlertChannel: Codable, Equatable, Identifiable, Sendable {
    public var name: String
    public var type: String
    public var events: [String]
    public var legacy: Bool?
    public var host: String?
    public var topic: String?
    public var chatId: String?

    public var id: String { name }
}

public struct AlertList: Codable, Equatable, Sendable {
    public var channels: [AlertChannel]
}

public struct AlertCreateRequest: Codable, Equatable, Sendable {
    public var type: String
    public var events: String?
    public var name: String?
    public var host: String?
    public var port: Int?
    public var user: String?
    public var password: String?
    public var sender: String?
    public var to: String?
    public var token: String?
    public var chatId: String?
    public var server: String?
    public var topic: String?
    public var url: String?
    public var secret: String?

    public init(type: String, events: String? = nil, name: String? = nil) {
        self.type = type
        self.events = events
        self.name = name
    }
}

public struct AlertAdded: Codable, Equatable, Sendable {
    public var channel: String?
}

public struct AlertTested: Codable, Equatable, Sendable {
    public var ok: Bool?
    public var code: String?
    public var failed: String?
}

public struct AlertRemoved: Codable, Equatable, Sendable {
    public var channel: String?
}

struct AlertTestRequest: Codable { var channel: String? }

public struct DeviceRolesDocument: Codable, Equatable, Sendable {
    public var defaultRole: String?

    enum CodingKeys: String, CodingKey { case defaultRole = "default" }

    public init(defaultRole: String? = nil) { self.defaultRole = defaultRole }
}

public struct DeviceInfo: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var name: String?
    public var roles: DeviceRolesDocument?
    public var servers: [String]?
    public var lastSeen: String?
    public var lastIp: String?
    public var revoked: Bool?
}

public struct DeviceList: Codable, Equatable, Sendable {
    public var devices: [DeviceInfo]
}

struct DeviceRolesRequest: Codable { var roles: DeviceRolesDocument }

public struct AuditEntry: Codable, Equatable, Sendable {
    public var at: String?
    public var action: String?
    public var device: String?
    public var server: String?
    public var ok: Bool?
    public var result: String?
}

public struct AuditLog: Codable, Equatable, Sendable {
    public var entries: [AuditEntry]
}

struct PairCodeRequest: Codable { var name: String?; var role: String }

public struct PairCode: Codable, Equatable, Sendable {
    public var pairingCode: String?
    public var expiresInS: Int?
    public var role: String?
}

public struct RemoteStatus: Codable, Equatable, Sendable {
    public var enabled: Bool?
    public var bind: String?
    public var fingerprint: String?
    public var devices: Int?
}

struct RemoteEnableRequest: Codable { var enabled: Bool }

public struct UpdateCheck: Codable, Equatable, Sendable {
    public var current: String?
    public var latest: String?
    public var updateAvailable: Bool?
    public var rollbackAvailable: Bool?
}

public struct DoctorCheck: Codable, Equatable, Sendable {
    public var server: String?
    public var name: String?
    public var ok: Bool?
    public var level: String?
    public var detail: String?
    public var fix: String?
}

public struct DoctorReport: Codable, Equatable, Sendable {
    public var checks: [DoctorCheck]
    public var errors: Int?
    public var warnings: Int?
}

public struct RouterConfig: Codable, Equatable, Sendable {
    public var enabled: Bool?
    public var port: Int?
    public var defaultServer: String?
    public var routes: [String: String]?
    public var allow: [String]?
    public var deny: [String]?

    enum CodingKeys: String, CodingKey {
        case enabled, port, routes, allow, deny
        case defaultServer = "default"
    }
}

public struct RouterStatus: Codable, Equatable, Sendable {
    public var config: RouterConfig?
    public var pendingRestart: [String]?

    enum CodingKeys: String, CodingKey {
        case config
        case pendingRestart = "pending_restart"
    }
}

struct RouterTargetRequest: Codable { var server: String }
struct RouterAccessRequest: Codable { var list: String; var action: String; var cidr: String }

public struct ModpackInfo: Codable, Equatable, Sendable {
    public var title: String?
    public var version: String?
    public var mcVersion: String?
    public var loader: String?
}

public struct ModpackInstallRequest: Codable, Equatable, Sendable {
    public var source: String
    public var acceptEula: Bool
    public var name: String?
    public var ram: String?
    public var port: Int?
    public var rconPort: Int?

    public init(source: String, acceptEula: Bool, name: String? = nil, ram: String? = nil,
                port: Int? = nil, rconPort: Int? = nil) {
        self.source = source
        self.acceptEula = acceptEula
        self.name = name
        self.ram = ram
        self.port = port
        self.rconPort = rconPort
    }
}

struct EmptyBody: Codable {}
