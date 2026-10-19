import AppKit
import MCManagerKit
import Observation
import SwiftUI

@MainActor
@Observable
final class AppModel {
    let errors = ErrorReporter()
    let connection: ConnectionViewModel
    private(set) var list: ServerListViewModel?
    private(set) var serviceMissing = false
    var createWizard: CreateServerViewModel?
    var pairingWizard: PairingWizardViewModel?
    @ObservationIgnored private var client: McClientProtocol?
    @ObservationIgnored private var details: [String: ServerDetailViewModel] = [:]

    init() {
        let store = ProfileStore(fileURL: ProfileStore.defaultFileURL(), secrets: KeychainSecretStore())
        connection = ConnectionViewModel(
            store: store, pairing: PairingClient(), localName: tr("This Mac"),
            local: { () -> McClientProtocol? in McClient.local() })
        connection.errors = errors
        connection.onChange = { [weak self] in
            Task { await self?.connect() }
        }
    }

    func connect() async {
        list?.stopPolling()
        list = nil
        details = [:]
        client = nil
        serviceMissing = false
        let made: McClientProtocol?
        do {
            made = try connection.makeClient()
        } catch {
            errors.report(error)
            serviceMissing = true
            return
        }
        guard let made else {
            serviceMissing = true
            return
        }
        client = made
        let model = ServerListViewModel(client: made, errors: errors)
        list = model
        await model.refresh()
        model.startPolling()
    }

    func select(_ id: String) {
        connection.selectedID = id
        connection.apply()
    }

    func removeSelectedRemote() {
        connection.removeSelected()
        connection.apply()
    }

    func detail(for name: String) -> ServerDetailViewModel? {
        if let existing = details[name] { return existing }
        guard let client else { return nil }
        let model = ServerDetailViewModel(client: client, errors: errors, name: name)
        details[name] = model
        return model
    }

    func openCreateWizard() {
        guard let client else { return }
        createWizard = CreateServerViewModel(client: client, errors: errors)
    }

    func openPairingWizard() {
        pairingWizard = PairingWizardViewModel(connection: connection, defaultName: ProcessInfo.processInfo.hostName)
    }

    func createFinished(_ name: String) async {
        createWizard = nil
        await list?.refresh()
        list?.selection = name
    }

    func pairingClosed() {
        let paired = pairingWizard?.step == .done
        pairingWizard = nil
        if paired { connection.apply() }
    }
}

@main
struct MCManagerApp: App {
    @State private var model = AppModel()

    init() {
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .frame(minWidth: 760, minHeight: 480)
        }
    }
}
