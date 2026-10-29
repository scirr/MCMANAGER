import MCManagerKit
import SwiftUI

struct ContentView: View {
    @Bindable var model: AppModel

    var body: some View {
        Group {
            if let list = model.list {
                ServerSplitView(model: model, list: list)
            } else if model.serviceMissing {
                ContentUnavailableView {
                    Label(tr("MC Manager not found"), systemImage: "externaldrive.badge.xmark")
                } description: {
                    Text(verbatim: tr("Install and start the MC Manager service, or set MCMANAGER_RUN_DIR."))
                } actions: {
                    Button(tr("Retry")) { Task { await model.connect() } }
                }
            } else if model.connectionFailed {
                ContentUnavailableView {
                    Label(tr("Not connected"), systemImage: "network.slash")
                } actions: {
                    Button(tr("Retry")) { Task { await model.connect() } }
                }
            } else {
                ProgressView()
            }
        }
        .task { await model.connect() }
        .toolbar { ConnectionMenu(model: model) }
        .sheet(isPresented: Binding(
            get: { model.createWizard != nil },
            set: { if !$0 { model.createWizard = nil } }
        )) {
            if let wizard = model.createWizard {
                CreateServerView(model: wizard, finished: { name in Task { await model.createFinished(name) } },
                                 cancel: { model.createWizard = nil })
            }
        }
        .sheet(isPresented: Binding(
            get: { model.system != nil },
            set: { if !$0 { model.system = nil } }
        )) {
            if let system = model.system {
                SystemView(model: system, close: { model.system = nil })
            }
        }
        .sheet(isPresented: Binding(
            get: { model.pairingWizard != nil },
            set: { if !$0 { model.pairingClosed() } }
        )) {
            if let wizard = model.pairingWizard {
                PairingView(model: wizard, close: { model.pairingClosed() })
            }
        }
        .alert(
            tr("Something went wrong"),
            isPresented: Binding(
                get: { model.errors.current != nil },
                set: { if !$0 { model.errors.dismiss() } }
            ),
            presenting: model.errors.current
        ) { _ in
            Button(tr("OK"), role: .cancel) {}
        } message: { error in
            Text(verbatim: message(for: error))
        }
    }
}

struct ServerSplitView: View {
    let model: AppModel
    @Bindable var list: ServerListViewModel

    var body: some View {
        NavigationSplitView {
            List(list.servers, id: \.name, selection: $list.selection) { server in
                ServerRow(server: server)
            }
            .navigationTitle(tr("Servers"))
            .navigationSplitViewColumnWidth(min: 200, ideal: 240)
            .overlay {
                if list.servers.isEmpty && !list.isLoading {
                    ContentUnavailableView(tr("No servers"), systemImage: "server.rack")
                }
            }
            .toolbar {
                Button {
                    model.openCreateWizard()
                } label: {
                    Label(tr("New server"), systemImage: "plus")
                }
                .help(tr("New server"))
                .accessibilityLabel(tr("New server"))
                Button {
                    model.openSystem()
                } label: {
                    Label(tr("System"), systemImage: "gearshape.2")
                }
                .help(tr("System"))
                .accessibilityLabel(tr("System"))
                Button {
                    Task { await list.refresh() }
                } label: {
                    Label(tr("Refresh"), systemImage: "arrow.clockwise")
                }
                .help(tr("Refresh"))
                .accessibilityLabel(tr("Refresh the server list"))
            }
        } detail: {
            if let name = list.selection, let detail = model.detail(for: name) {
                ServerDetailView(model: detail)
                    .id(name)
            } else {
                ContentUnavailableView(tr("Select a server"), systemImage: "sidebar.left")
            }
        }
    }
}

struct ServerRow: View {
    let server: ServerSnapshot

    var body: some View {
        HStack {
            Circle()
                .fill(color(for: server.state ?? ""))
                .frame(width: 10, height: 10)
                .accessibilityHidden(true)
            VStack(alignment: .leading) {
                Text(verbatim: server.name)
                Text(verbatim: stateLabel(server.error != nil ? "error" : server.state ?? ""))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
        .tag(server.name)
    }

    private func color(for state: String) -> Color {
        switch state {
        case "running": return .green
        case "starting", "sleeping", "maintenance": return .orange
        case "crashed", "error": return .red
        default: return .gray
        }
    }
}

struct ConnectionMenu: ToolbarContent {
    let model: AppModel

    var body: some ToolbarContent {
        ToolbarItem(placement: .navigation) {
            Menu {
                ForEach(model.connection.targets) { target in
                    Button {
                        model.select(target.id)
                    } label: {
                        if target.id == model.connection.selectedID {
                            Label(target.isLocal ? tr("This Mac") : target.name, systemImage: "checkmark")
                        } else {
                            Text(verbatim: target.isLocal ? tr("This Mac") : target.name)
                        }
                    }
                }
                Divider()
                Button(tr("Add a remote...")) { model.openPairingWizard() }
                if !model.connection.selected.isLocal {
                    Button(tr("Remove this remote"), role: .destructive) { model.removeSelectedRemote() }
                }
            } label: {
                Label(model.connection.selected.isLocal ? tr("This Mac") : model.connection.selected.name,
                      systemImage: model.connection.selected.isLocal ? "desktopcomputer" : "network")
            }
            .help(tr("Connection"))
            .accessibilityLabel(tr("Connection"))
        }
    }
}
