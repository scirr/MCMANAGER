import Foundation
import Observation

public struct AppNotice: Equatable, Sendable {
    public let kind: String
    public let server: String
    public let detail: String
    public var id: String { kind + "-" + server }
}

@MainActor
@Observable
public final class NotificationPrefs {
    public static let kinds = ["crash", "backup_failed", "join"]
    private static let alertKinds: [String: String] = [
        "crash": "crash", "crash_loop": "crash", "backup_failed": "backup_failed",
    ]

    public private(set) var enabled: [String: Bool] = [:]

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let key: String

    public init(defaults: UserDefaults = .standard, key: String = "notification_kinds") {
        self.defaults = defaults
        self.key = key
        let saved = defaults.dictionary(forKey: key) as? [String: Bool] ?? [:]
        for kind in Self.kinds { enabled[kind] = saved[kind] ?? true }
    }

    public func isEnabled(_ kind: String) -> Bool { enabled[kind] ?? false }

    public func set(_ kind: String, _ value: Bool) {
        guard enabled[kind] != nil, enabled[kind] != value else { return }
        enabled[kind] = value
        defaults.set(enabled, forKey: key)
    }

    public func notice(for event: ConsoleEvent) -> AppNotice? {
        guard let data = event.data.data(using: .utf8),
              let payload = try? Coding.plainDecoder.decode(EventPayload.self, from: data) else { return nil }
        let server = payload.server ?? ""
        switch payload.type {
        case "alert":
            guard let name = payload.event, let kind = Self.alertKinds[name], isEnabled(kind) else { return nil }
            return AppNotice(kind: name, server: server, detail: payload.detail ?? "")
        case "players":
            guard isEnabled("join"), let joined = payload.joined, !joined.isEmpty else { return nil }
            return AppNotice(kind: "join", server: server, detail: joined.joined(separator: ", "))
        default:
            return nil
        }
    }
}

struct EventPayload: Decodable {
    var type: String?
    var server: String?
    var event: String?
    var detail: String?
    var joined: [String]?
}

@MainActor
public final class EventWatcher {
    public var retryDelay: Duration = .seconds(5)

    private let client: McClientProtocol
    private let prefs: NotificationPrefs
    private let deliver: @MainActor (AppNotice) -> Void
    private var task: Task<Void, Never>?

    public init(client: McClientProtocol, prefs: NotificationPrefs, deliver: @escaping @MainActor (AppNotice) -> Void) {
        self.client = client
        self.prefs = prefs
        self.deliver = deliver
    }

    public func consume() async {
        do {
            for try await event in client.streamEvents() {
                if let notice = prefs.notice(for: event) { deliver(notice) }
            }
        } catch {}
    }

    public func start() {
        stop()
        task = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.consume()
                try? await Task.sleep(for: self.retryDelay)
            }
        }
    }

    public func stop() {
        task?.cancel()
        task = nil
    }
}
