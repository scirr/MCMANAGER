import Foundation

public struct BackupEntry: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var file: String?
    public var type: String?
    public var created: String?
    public var createdTs: Int?
    public var size: Int?
    public var encrypted: Bool?
}

public struct BackupList: Codable, Equatable, Sendable {
    public var backups: [BackupEntry]
}

struct BackupRestoreRequest: Codable { var confirm: Bool }

public struct ModEntry: Codable, Equatable, Identifiable, Sendable {
    public var file: String
    public var modId: String?
    public var name: String?
    public var version: String?
    public var loader: String?
    public var source: String?
    public var project: String?
    public var trackedVersion: String?
    public var server: Bool?
    public var modpack: Bool?
    public var addsBlocks: Bool?

    enum CodingKeys: String, CodingKey {
        case file, modId = "id", name, version, loader, source, project, trackedVersion, server, modpack, addsBlocks
    }

    public var id: String { file }
}

public struct ModList: Codable, Equatable, Sendable {
    public var mods: [ModEntry]
}

struct ModAddRequest: Codable { var ref: String; var source: String? }
struct ModUpdateRequest: Codable { var name: String? }

public struct ModRemoved: Codable, Equatable, Sendable {
    public var file: String?
    public var restartRequired: Bool?
}

public struct DatapackEntry: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var file: String
    public var enabled: Bool?
    public var order: Int?
    public var worldgen: Bool?
    public var problem: String?
}

public struct DatapackList: Codable, Equatable, Sendable {
    public var running: Bool?
    public var packs: [DatapackEntry]
}

struct DatapackSetRequest: Codable {
    var enabled: Bool
    var first: Bool?
    var last: Bool?
    var beforeVanilla: Bool?
}

public struct DatapackSet: Codable, Equatable, Sendable {
    public var pack: String?
    public var restartRequired: Bool?
}

public struct WorldDimension: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var sizeBytes: Int?
}

public struct WorldList: Codable, Equatable, Sendable {
    public var level: String?
    public var sizeBytes: Int?
    public var dimensions: [WorldDimension]
}

public struct PregenProgress: Codable, Equatable, Sendable {
    public var progress: String?
}

struct PregenRequest: Codable { var radius: Int; var center: String? }

public struct Pregen: Codable, Equatable, Sendable {
    public var radius: Int?
    public var progress: String?
}

struct WorldResetRequest: Codable { var confirmed: Bool; var includeOverworld: Bool? }

public struct TaskLastResult: Codable, Equatable, Sendable {
    public var ok: Bool?
    public var code: String?
}

public struct TaskEntry: Codable, Equatable, Identifiable, Sendable {
    public var id: Int
    public var name: String?
    public var cron: String?
    public var action: String?
    public var command: String?
    public var enabled: Bool?
    public var warn: [Int]?
    public var lastRun: String?
    public var nextRun: String?
    public var lastResult: TaskLastResult?
}

public struct TaskList: Codable, Equatable, Sendable {
    public var tasks: [TaskEntry]
}

public struct TaskCreated: Codable, Equatable, Sendable {
    public var task: TaskEntry?
}

public struct TaskCreateRequest: Codable, Equatable, Sendable {
    public var cron: String
    public var action: String
    public var name: String?
    public var command: String?
    public var warn: String?

    public init(cron: String, action: String, name: String? = nil, command: String? = nil, warn: String? = nil) {
        self.cron = cron
        self.action = action
        self.name = name
        self.command = command
        self.warn = warn
    }
}

struct TaskPatchRequest: Codable { var enabled: Bool }
struct TaskRunRequest: Codable { var skipWarn: Bool? }

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case null
    case other

    public init(from decoder: Decoder) throws {
        let single = try decoder.singleValueContainer()
        if single.decodeNil() {
            self = .null
        } else if let value = try? single.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? single.decode(Double.self) {
            self = .number(value)
        } else if let value = try? single.decode(String.self) {
            self = .string(value)
        } else {
            self = .other
        }
    }

    public func encode(to encoder: Encoder) throws {
        var single = encoder.singleValueContainer()
        switch self {
        case .string(let value): try single.encode(value)
        case .number(let value): try single.encode(value)
        case .bool(let value): try single.encode(value)
        case .null, .other: try single.encodeNil()
        }
    }

    public var text: String {
        switch self {
        case .string(let value): return value
        case .number(let value):
            return value == value.rounded() && abs(value) < 1e15 ? String(Int64(value)) : String(value)
        case .bool(let value): return value ? "1" : "0"
        case .null, .other: return ""
        }
    }

    public var integer: Int? {
        if case .number(let value) = self { return Int(exactly: value) }
        return nil
    }
}

public struct ConfigDocument: Codable, Equatable, Sendable {
    public var config: [String: JSONValue]
    public var secretsSet: [String]

    enum CodingKeys: String, CodingKey {
        case config
        case secretsSet = "secrets_set"
    }
}

struct ConfigSetRequest: Codable { var value: String }

public struct ConfigSet: Codable, Equatable, Sendable {
    public var key: String?
    public var restartRequired: Bool?
}

struct ModeRequest: Codable { var mode: String }

public struct ScheduleRequest: Codable, Equatable, Sendable {
    public var openHour: Int
    public var openMinute: Int
    public var closeHour: Int
    public var closeMinute: Int

    public init(openHour: Int, openMinute: Int, closeHour: Int, closeMinute: Int) {
        self.openHour = openHour
        self.openMinute = openMinute
        self.closeHour = closeHour
        self.closeMinute = closeMinute
    }
}

public struct SleepSettings: Codable, Equatable, Sendable {
    public var enabled: Bool
    public var afterS: Int
    public var joinMode: String?
    public var holdTimeoutS: Int?
    public var freeze: Bool?
    public var notes: [String]?
}

public struct SleepSettingsRequest: Codable, Equatable, Sendable {
    public var enabled: Bool?
    public var afterS: Int?
    public var joinMode: String?
    public var freeze: Bool?

    public init(enabled: Bool? = nil, afterS: Int? = nil, joinMode: String? = nil, freeze: Bool? = nil) {
        self.enabled = enabled
        self.afterS = afterS
        self.joinMode = joinMode
        self.freeze = freeze
    }
}

public struct JavaServerChoice: Codable, Equatable, Sendable {
    public var server: String
    public var java: JSONValue?
    public var minecraft: String?
}

public struct JavaRuntimes: Codable, Equatable, Sendable {
    public var runtimes: [String: String]
    public var servers: [JavaServerChoice]
}

struct JavaUseRequest: Codable { var choice: String }

public struct JavaUsed: Codable, Equatable, Sendable {
    public var restartRequired: Bool?
}

public struct CreateServerRequest: Codable, Equatable, Sendable {
    public var name: String
    public var loader: String
    public var acceptEula: Bool
    public var version: String?
    public var ram: String?
    public var port: Int?
    public var rconPort: Int?

    public init(name: String, loader: String, acceptEula: Bool, version: String? = nil,
                ram: String? = nil, port: Int? = nil, rconPort: Int? = nil) {
        self.name = name
        self.loader = loader
        self.acceptEula = acceptEula
        self.version = version
        self.ram = ram
        self.port = port
        self.rconPort = rconPort
    }
}
