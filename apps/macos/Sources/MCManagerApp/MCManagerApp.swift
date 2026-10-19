import AppKit
import MCManagerKit
import Observation
import SwiftUI

@MainActor
@Observable
final class AppModel {
    let errors = ErrorReporter()
    private(set) var list: ServerListViewModel?
    private(set) var serviceMissing = false
    @ObservationIgnored private var client: McClient?
    @ObservationIgnored private var details: [String: ServerDetailViewModel] = [:]

    func connect() async {
        guard let client = McClient.local() else {
            serviceMissing = true
            return
        }
        serviceMissing = false
        self.client = client
        let model = list ?? ServerListViewModel(client: client, errors: errors)
        list = model
        await model.refresh()
        model.startPolling()
    }

    func detail(for name: String) -> ServerDetailViewModel? {
        if let existing = details[name] { return existing }
        guard let client else { return nil }
        let model = ServerDetailViewModel(client: client, errors: errors, name: name)
        details[name] = model
        return model
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
