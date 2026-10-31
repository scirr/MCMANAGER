import MCManagerKit
import SwiftUI

struct ModsView: View {
    @Bindable var model: ModsViewModel
    @State private var pending: ModItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                TextField(tr("Mod name, URL or .jar path"), text: $model.newReference)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await model.add() } }
                Picker(tr("Source"), selection: $model.selectedSource) {
                    ForEach(ModsViewModel.sources, id: \.self) { source in
                        Text(verbatim: sourceLabel(source)).tag(source)
                    }
                }
                .frame(maxWidth: 160)
                Button {
                    Task { await model.add() }
                } label: {
                    Label(tr("Add"), systemImage: "plus")
                }
                .disabled(!model.tab.canAct || model.newReference.trimmingCharacters(in: .whitespaces).isEmpty)
                Button(tr("Update all")) { Task { await model.updateAll() } }
                    .disabled(!model.tab.canAct)
                Button(tr("Update the modpack")) { Task { await model.updateModpack() } }
                    .disabled(!model.tab.canAct)
                IconButton(title: tr("Refresh"), symbol: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
            }
            TabStatusView(tab: model.tab)
            List(model.items) { item in
                HStack {
                    VStack(alignment: .leading) {
                        Text(verbatim: item.name)
                        Text(verbatim: details(item)).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if !model.tab.isReadOnly {
                        IconButton(title: String(format: tr("Remove the mod %@"), item.name), symbol: "trash",
                                   role: .destructive, enabled: !model.tab.isBusy) {
                            pending = item
                        }
                    }
                }
            }
            .overlay {
                if model.isEmpty { ContentUnavailableView(tr("No mod installed."), systemImage: "puzzlepiece.extension") }
            }
        }
        .padding(.top, 8)
        .task { await model.refresh() }
        .alert(
            tr("Remove this mod?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { item in
            Button(tr("Remove"), role: .destructive) {
                Task { await model.remove(item.file, confirmed: true) }
            }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { item in
            Text(verbatim: removalMessage(item))
        }
    }

    private func details(_ item: ModItem) -> String {
        var parts = [item.version, item.source].filter { !$0.isEmpty }
        if item.addsBlocks { parts.append(tr("adds blocks")) }
        return parts.joined(separator: " - ")
    }

    private func removalMessage(_ item: ModItem) -> String {
        var text = String(format: tr("%@ will be moved to the quarantine folder; nothing is deleted."), item.name)
        if item.addsBlocks {
            text += "\n\n" + tr("This mod adds blocks to the world. Removing it turns them into air and the world saves that change.")
        }
        return text
    }
}
