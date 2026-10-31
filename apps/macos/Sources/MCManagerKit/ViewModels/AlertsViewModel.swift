import Foundation
import Observation

public struct AlertRow: Equatable, Identifiable, Sendable {
    public let name: String
    public let type: String
    public let events: [String]
    public let legacy: Bool
    public let target: String
    public var id: String { name }
}

public struct AlertField: Equatable, Sendable {
    public let key: String
    public let secret: Bool
}

@MainActor
@Observable
public final class AlertsViewModel {
    public static let types = ["email", "telegram", "ntfy", "webhook", "discord"]
    public static let events = ["start", "stop", "crash", "crash_loop", "backup_failed", "update", "sleep", "wake"]

    public static func fields(for type: String) -> [AlertField] {
        switch type {
        case "email":
            return [AlertField(key: "host", secret: false), AlertField(key: "port", secret: false),
                    AlertField(key: "user", secret: false), AlertField(key: "password", secret: true),
                    AlertField(key: "sender", secret: false), AlertField(key: "to", secret: false)]
        case "telegram":
            return [AlertField(key: "token", secret: true), AlertField(key: "chat_id", secret: false)]
        case "ntfy":
            return [AlertField(key: "server", secret: false), AlertField(key: "topic", secret: false),
                    AlertField(key: "token", secret: true)]
        case "webhook":
            return [AlertField(key: "url", secret: true), AlertField(key: "secret", secret: true)]
        case "discord":
            return [AlertField(key: "url", secret: true)]
        default:
            return []
        }
    }

    public private(set) var rows: [AlertRow] = []
    public var newType = "ntfy"
    public var values: [String: String] = [:]
    public var selectedEvents: Set<String> = []
    public var channelName = ""
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter
    @ObservationIgnored private let server: String

    public init(client: McClientProtocol, errors: ErrorReporter, server: String) {
        self.client = client
        self.errors = errors
        self.server = server
        tab = TabRunner(client: client, errors: errors, server: server)
    }

    public var isEmpty: Bool { rows.isEmpty }
    public var fields: [AlertField] { Self.fields(for: newType) }

    public func refresh() async {
        await tab.read {
            let list = try await client.alertChannels(server)
            rows = list.channels.map { channel in
                AlertRow(name: channel.name, type: channel.type, events: channel.events,
                         legacy: channel.legacy ?? false,
                         target: channel.topic ?? channel.host ?? channel.chatId ?? "")
            }
        }
    }

    public func add() async {
        guard Self.types.contains(newType) else { return }
        var request = AlertCreateRequest(
            type: newType,
            events: Self.events.filter { selectedEvents.contains($0) }.joined(separator: ",").nilIfEmpty,
            name: channelName.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty)
        for field in fields {
            let value = (values[field.key] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if value.isEmpty { continue }
            switch field.key {
            case "host": request.host = value
            case "port":
                guard let port = Int(value), (1...65535).contains(port) else {
                    errors.show("bad_port")
                    return
                }
                request.port = port
            case "user": request.user = value
            case "password": request.password = value
            case "sender": request.sender = value
            case "to": request.to = value
            case "token": request.token = value
            case "chat_id": request.chatId = value
            case "server": request.server = value
            case "topic": request.topic = value
            case "url": request.url = value
            case "secret": request.secret = value
            default: break
            }
        }
        let done = await tab.write { _ = try await self.client.addAlertChannel(self.server, request: request) }
        if done {
            values = [:]
            selectedEvents = []
            channelName = ""
            tab.markDone("alert_added")
            await refresh()
        }
    }

    public func test(_ channel: String?) async {
        let done = await tab.write {
            let result = try await self.client.testAlerts(self.server, channel: channel)
            if result.ok == false {
                throw ApiError(code: result.code ?? "alert_test_failed", message: result.failed ?? "", status: 200)
            }
        }
        if done { tab.markDone("alert_tested") }
    }

    public func remove(_ channel: String?, confirmed: Bool) async {
        guard confirmed, let channel, !channel.isEmpty else { return }
        if await tab.write({ _ = try await self.client.removeAlertChannel(self.server, channel: channel) }) {
            tab.markDone("alert_removed")
            await refresh()
        }
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
