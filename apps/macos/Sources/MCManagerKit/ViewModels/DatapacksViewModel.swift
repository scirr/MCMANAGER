import Foundation
import Observation

public struct DatapackItem: Equatable, Identifiable, Sendable {
    public let file: String
    public let packId: String
    public let enabled: Bool
    public let canToggle: Bool
    public let problem: String?
    public let worldgen: Bool
    public var id: String { file }
}

@MainActor
@Observable
public final class DatapacksViewModel {
    public static let placements = ["default", "first", "last", "before_vanilla"]

    public var placement = "default"
    public private(set) var items: [DatapackItem] = []
    public private(set) var serverRunning = false
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
            let list = try await client.listDatapacks(server)
            serverRunning = list.running ?? false
            items = list.packs.map {
                DatapackItem(file: $0.file, packId: $0.id, enabled: $0.enabled == true, canToggle: $0.problem == nil,
                             problem: $0.problem, worldgen: $0.worldgen ?? false)
            }
        }
    }

    public func setEnabled(_ file: String?, enabled: Bool) async {
        guard let file, !file.isEmpty, !tab.isBusy else { return }
        tab.setBusy(true)
        await tab.write {
            let set = try await self.client.setDatapackEnabled(self.server, pack: file, enabled: enabled,
                                                              placement: enabled && self.placement != "default" ? self.placement : nil)
            if set.restartRequired == true { self.tab.restartRequired = true }
        }
        tab.setBusy(false)
        await refresh()
    }
}
