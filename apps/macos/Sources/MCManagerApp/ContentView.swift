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
            } else {
                ProgressView()
            }
        }
        .task { await model.connect() }
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
