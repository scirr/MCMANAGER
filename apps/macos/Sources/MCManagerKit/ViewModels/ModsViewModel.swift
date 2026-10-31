import Foundation
import Observation

public struct ModItem: Equatable, Identifiable, Sendable {
    public let file: String
    public let name: String
    public let version: String
    public let source: String
    public let addsBlocks: Bool
    public let inModpack: Bool
    public var id: String { file }
}

@MainActor
@Observable
public final class ModsViewModel {
    public static let sources = ["auto", "modrinth", "curseforge", "hangar"]

    public private(set) var items: [ModItem] = []
    public var newReference = ""
    public var selectedSource = "auto"
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
            let mods = try await client.listMods(server)
            items = mods.map { mod in
                let label = (mod.name?.isEmpty == false ? mod.name : nil) ?? mod.modId ?? mod.file
                return ModItem(file: mod.file, name: label, version: mod.version ?? "", source: mod.source ?? "",
                               addsBlocks: mod.addsBlocks ?? false, inModpack: mod.modpack ?? false)
            }
        }
    }

    public func add() async {
        let reference = newReference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !reference.isEmpty else { return }
        let source = selectedSource.isEmpty || selectedSource == "auto" ? nil : selectedSource
        let done = await tab.runJob("add") {
            try await self.client.addMod(self.server, reference: reference, source: source)
        }
        if done {
            newReference = ""
            tab.restartRequired = true
        }
        await refresh()
    }

    public func updateAll() async {
        let done = await tab.runJob("update") { try await self.client.updateMods(self.server, mod: nil) }
        if done { tab.restartRequired = true }
        await refresh()
    }

    public func remove(_ file: String?, confirmed: Bool) async {
        guard confirmed, let file, !file.isEmpty, !tab.isBusy else { return }
        let blocks = items.first { $0.file == file }?.addsBlocks ?? false
        let done = await tab.write {
            let removed = try await self.client.removeMod(self.server, mod: file, confirmBlocks: blocks)
            if removed.restartRequired == true { self.tab.restartRequired = true }
        }
        if done {
            tab.markDone("remove")
            await refresh()
        }
    }

    public func updateModpack() async {
        let done = await tab.runJob("modpack_updated") { try await self.client.updateModpack(self.server) }
        if done {
            if tab.lastJob?.result?.code == "pack_up_to_date" {
                tab.markDone("modpack_current")
            } else {
                tab.restartRequired = true
            }
        }
        await refresh()
    }
}
