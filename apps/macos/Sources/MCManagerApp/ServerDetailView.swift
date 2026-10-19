import MCManagerKit
import SwiftUI

struct ServerDetailView: View {
    let model: ServerDetailViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            TabView {
                ConsoleView(model: model.console)
                    .tabItem { Label(tr("Console"), systemImage: "terminal") }
                PlayersView(model: model.players)
                    .tabItem { Label(tr("Players"), systemImage: "person.2") }
                BackupsView(model: model.backups)
                    .tabItem { Label(tr("Backups"), systemImage: "externaldrive") }
                ModsView(model: model.mods)
                    .tabItem { Label(tr("Mods"), systemImage: "puzzlepiece.extension") }
                DatapacksView(model: model.datapacks)
                    .tabItem { Label(tr("Datapacks"), systemImage: "shippingbox") }
                WorldView(model: model.world)
                    .tabItem { Label(tr("World"), systemImage: "globe") }
                TasksView(model: model.tasks)
                    .tabItem { Label(tr("Tasks"), systemImage: "calendar.badge.clock") }
                SettingsView(model: model.settings)
                    .tabItem { Label(tr("Settings"), systemImage: "gearshape") }
            }
        }
        .padding()
        .navigationTitle(model.name)
        .toolbar { actions }
        .task {
            await model.refresh()
            model.console.start()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                if !model.isBusy { await model.refresh() }
            }
        }
        .onDisappear { model.console.stop() }
    }

    private var header: some View {
        HStack(spacing: 24) {
            VStack(alignment: .leading) {
                Text(verbatim: model.name).font(.title2.bold())
                Text(verbatim: stateLabel(model.state)).foregroundStyle(.secondary)
            }
            Spacer()
            stat(tr("Version"), model.version.isEmpty ? "-" : model.version)
            stat(tr("Memory"), model.ramText)
            stat(tr("Players"), model.players.onlineText)
        }
    }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(alignment: .trailing) {
            Text(verbatim: title).font(.caption).foregroundStyle(.secondary)
            Text(verbatim: value).monospacedDigit()
        }
        .accessibilityElement(children: .combine)
    }

    @ToolbarContentBuilder
    private var actions: some ToolbarContent {
        ToolbarItemGroup {
            action(tr("Start"), "play.fill", enabled: model.canStart) { await model.start() }
            action(tr("Stop"), "stop.fill", enabled: model.canStop) { await model.stop() }
            action(tr("Restart"), "arrow.triangle.2.circlepath", enabled: model.canRestart) { await model.restart() }
            action(tr("Resume"), "playpause.fill", enabled: model.canResume) { await model.resume() }
            if model.isBusy { ProgressView().controlSize(.small) }
        }
    }

    private func action(_ title: String, _ symbol: String, enabled: Bool,
                        run: @escaping () async -> Void) -> some View {
        Button {
            Task { await run() }
        } label: {
            Label(title, systemImage: symbol)
        }
        .disabled(!enabled)
        .help(title)
        .accessibilityLabel(title)
    }
}
