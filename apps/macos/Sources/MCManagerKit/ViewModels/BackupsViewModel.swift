import Foundation
import Observation

public struct BackupItem: Equatable, Identifiable, Sendable {
    public let id: String
    public let date: String
    public let sizeText: String
    public let origin: String
    public let encrypted: Bool
}

@MainActor
@Observable
public final class BackupsViewModel {
    public private(set) var items: [BackupItem] = []
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

    public var isEmpty: Bool { items.isEmpty }

    public func refresh() async {
        await errors.attempt {
            let backups = try await client.listBackups(server)
            items = backups.map {
                BackupItem(id: $0.id, date: TabRunner.stamp($0.created), sizeText: TabRunner.formatSize($0.size),
                           origin: $0.type ?? "", encrypted: $0.encrypted ?? false)
            }
        }
    }

    public func create() async {
        await tab.runJob("create") { try await self.client.createBackup(self.server) }
        await refresh()
    }

    public func restore(_ id: String?, confirmed: Bool) async {
        guard confirmed, let id, !id.isEmpty else { return }
        await tab.runJob("restore") { try await self.client.restoreBackup(self.server, backup: id, confirm: true) }
        await refresh()
    }
}
