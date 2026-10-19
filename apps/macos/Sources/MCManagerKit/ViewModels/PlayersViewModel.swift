import Foundation
import Observation

@MainActor
@Observable
public final class PlayersViewModel {
    public static let kinds = ["whitelist", "op", "ban", "banip"]

    public private(set) var online: [String] = []
    public private(set) var onlineText = "-"
    public private(set) var entries: [PlayerListEntry] = []
    public var selectedKind = "whitelist"
    public var newSubject = ""
    public var reason = ""
    public private(set) var isReadOnly = false

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter
    @ObservationIgnored private let server: String

    public init(client: McClientProtocol, errors: ErrorReporter, server: String) {
        self.client = client
        self.errors = errors
        self.server = server
    }

    private func write(_ work: () async throws -> Void) async -> Bool {
        await errors.attempt {
            do {
                try await work()
            } catch let error as ApiError where error.status == 403 {
                isReadOnly = true
                throw error
            }
        }
    }

    public func refresh() async {
        await loadOnline()
        await loadList()
    }

    public func loadOnline() async {
        do {
            let players = try await client.onlinePlayers(server)
            online = players.players
            onlineText = players.max.map { "\(players.online)/\($0)" } ?? String(players.online)
        } catch let error as ApiError where ["server_offline", "rcon_failed", "rcon_error"].contains(error.code) {
            online = []
            onlineText = "-"
        } catch {
            errors.report(error)
        }
    }

    public func loadList() async {
        await errors.attempt {
            entries = try await client.playerList(server, kind: selectedKind).entries
        }
    }

    public func selectKind(_ kind: String) async {
        selectedKind = kind
        await loadList()
    }

    public func add() async {
        let subject = newSubject.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !subject.isEmpty else { return }
        let text = reason.trimmingCharacters(in: .whitespacesAndNewlines)
        let done = await write {
            _ = try await client.addToList(server, kind: selectedKind, subject: subject, reason: text.isEmpty ? nil : text)
        }
        if done {
            newSubject = ""
            reason = ""
            await loadList()
        }
    }

    public func remove(_ subject: String) async {
        guard !subject.isEmpty else { return }
        let done = await write {
            _ = try await client.removeFromList(server, kind: selectedKind, subject: subject)
        }
        if done { await loadList() }
    }

    public func kick(_ player: String) async {
        guard !player.isEmpty else { return }
        let done = await write {
            _ = try await client.kick(server, player: player, reason: nil)
        }
        if done { await loadOnline() }
    }
}
