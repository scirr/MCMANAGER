import Foundation
import Observation

public struct DimensionItem: Equatable, Identifiable, Sendable {
    public let id: String
    public let sizeText: String
}

@MainActor
@Observable
public final class WorldViewModel {
    public private(set) var dimensions: [DimensionItem] = []
    public private(set) var totalSizeText = "-"
    public private(set) var pregenText = ""
    public var radiusText = "1000"
    public var centerText = ""
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

    public func refresh() async {
        await errors.attempt {
            let worlds = try await client.listWorlds(server)
            dimensions = worlds.dimensions.map { DimensionItem(id: $0.id, sizeText: TabRunner.formatSize($0.sizeBytes)) }
            totalSizeText = TabRunner.formatSize(worlds.sizeBytes)
        }
        await refreshPregen()
    }

    public func refreshPregen() async {
        do {
            pregenText = try await client.pregenStatus(server).progress ?? ""
        } catch let error as ApiError where error.status == 409 || error.status == 503 {
            pregenText = ""
        } catch {
            errors.report(error)
        }
    }

    public func startPregen() async {
        guard let radius = Int(radiusText.trimmingCharacters(in: .whitespaces)), radius > 0 else {
            errors.show("invalid_radius")
            return
        }
        let center = centerText.trimmingCharacters(in: .whitespaces)
        let done = await tab.write {
            let started = try await self.client.startPregen(self.server, radius: radius, center: center.isEmpty ? nil : center)
            self.pregenText = started.progress ?? ""
        }
        if done { tab.markDone("pregen") }
    }

    public func reset(_ dimension: String?, confirmed: Bool) async {
        guard confirmed, let dimension, !dimension.isEmpty else { return }
        await tab.runJob("reset") {
            try await self.client.resetDimension(self.server, dimension: dimension, confirmed: true,
                                                  includeOverworld: dimension == "overworld")
        }
        await refresh()
    }
}
