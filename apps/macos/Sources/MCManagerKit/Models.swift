import Foundation

public struct ServerSnapshotError: Codable, Equatable, Sendable {
    public var code: String?
    public init(code: String? = nil) { self.code = code }
}

public struct ServerSnapshot: Codable, Equatable, Sendable {
    public var ok: Bool?
    public var code: String?
    public var id: Int?
    public var name: String
    public var server: String?
    public var active: Bool?
    public var state: String?
    public var mode: String?
    public var loader: String?
    public var version: String?
    public var port: Int?
    public var pid: Int?
    public var rssKb: Int?
    public var uptimeS: Int?
    public var frozen: Bool?
    public var maintenance: Bool?
    public var stopReason: String?
    public var error: ServerSnapshotError?

    public init(name: String, state: String? = nil, loader: String? = nil, version: String? = nil,
                rssKb: Int? = nil, active: Bool? = nil, error: ServerSnapshotError? = nil) {
        self.name = name
        self.state = state
        self.loader = loader
        self.version = version
        self.rssKb = rssKb
        self.active = active
        self.error = error
    }
}

public struct ServerList: Codable, Equatable, Sendable {
    public var active: String?
    public var servers: [ServerSnapshot]
}

public struct PlayersOnline: Codable, Equatable, Sendable {
    public var server: String?
    public var state: String?
    public var online: Int
    public var max: Int?
    public var players: [String]
}

public struct PlayerListEntry: Codable, Equatable, Identifiable, Sendable {
    public var name: String?
    public var uuid: String?
    public var ip: String?
    public var reason: String?
    public var level: Int?
    public var expires: String?

    public init(name: String? = nil, uuid: String? = nil, ip: String? = nil, reason: String? = nil) {
        self.name = name
        self.uuid = uuid
        self.ip = ip
        self.reason = reason
    }

    public var subject: String { name ?? ip ?? "" }
    public var id: String { subject }
}

public struct PlayerListing: Codable, Equatable, Sendable {
    public var server: String?
    public var enabled: Bool?
    public var entries: [PlayerListEntry]
}

public struct OperationResult: Codable, Equatable, Sendable {
    public var ok: Bool?
    public var code: String?
    public var message: String?
    public var server: String?
    public var subject: String?
    public var changed: Bool?
    public var via: String?
    public var output: String?
    public var mode: String?
}

public struct JobResult: Codable, Equatable, Sendable {
    public var ok: Bool?
    public var code: String?
    public var message: String?
}

public struct Job: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var kind: String
    public var state: String
    public var code: String?
    public var progress: Int?
    public var server: String?
    public var result: JobResult?

    public init(id: String, kind: String, state: String, code: String? = nil,
                progress: Int? = nil, server: String? = nil, result: JobResult? = nil) {
        self.id = id
        self.kind = kind
        self.state = state
        self.code = code
        self.progress = progress
        self.server = server
        self.result = result
    }

    public var isFinished: Bool { ["succeeded", "failed", "cancelled"].contains(state) }
}

public struct JobList: Codable, Equatable, Sendable {
    public var jobs: [Job]
}

public struct StopRequest: Codable, Equatable, Sendable {
    public var force: Bool?
    public var quiet: Bool?
    public var reason: String?

    public init(force: Bool? = nil, quiet: Bool? = nil, reason: String? = nil) {
        self.force = force
        self.quiet = quiet
        self.reason = reason
    }
}

struct ConsoleCommand: Codable { var command: String }
struct PlayerListAdd: Codable { var subject: String; var reason: String? }
struct KickRequest: Codable { var player: String; var reason: String? }

public struct ConsoleEvent: Equatable, Sendable {
    public var id: String?
    public var name: String
    public var data: String

    public init(id: String? = nil, name: String, data: String) {
        self.id = id
        self.name = name
        self.data = data
    }
}

enum Coding {
    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()
}
