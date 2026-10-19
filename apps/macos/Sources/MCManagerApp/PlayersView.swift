import MCManagerKit
import SwiftUI

struct PlayersView: View {
    @Bindable var model: PlayersViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(verbatim: String(format: tr("Online now: %@"), model.onlineText)).font(.headline)
            List(model.online, id: \.self) { player in
                HStack {
                    Text(verbatim: player)
                    Spacer()
                    if !model.isReadOnly {
                        Button {
                            Task { await model.kick(player) }
                        } label: {
                            Label(tr("Kick"), systemImage: "person.fill.xmark")
                        }
                        .labelStyle(.iconOnly)
                        .help(tr("Kick"))
                        .accessibilityLabel(String(format: tr("Kick %@"), player))
                    }
                }
            }
            .frame(minHeight: 80, maxHeight: 160)

            Picker(tr("List"), selection: Binding(
                get: { model.selectedKind },
                set: { kind in Task { await model.selectKind(kind) } }
            )) {
                ForEach(PlayersViewModel.kinds, id: \.self) { kind in
                    Text(verbatim: kindLabel(kind)).tag(kind)
                }
            }
            .pickerStyle(.segmented)

            List(model.entries, id: \.subject) { entry in
                HStack {
                    VStack(alignment: .leading) {
                        Text(verbatim: entry.subject)
                        if let reason = entry.reason, !reason.isEmpty {
                            Text(verbatim: reason).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if !model.isReadOnly {
                        Button {
                            Task { await model.remove(entry.subject) }
                        } label: {
                            Label(tr("Remove"), systemImage: "trash")
                        }
                        .labelStyle(.iconOnly)
                        .help(tr("Remove"))
                        .accessibilityLabel(String(format: tr("Remove %@"), entry.subject))
                    }
                }
            }

            if model.isReadOnly {
                Label(tr("This device is not allowed to change this."), systemImage: "lock")
                    .foregroundStyle(.secondary)
            } else {
                HStack {
                    TextField(tr("Player or address"), text: $model.newSubject)
                    TextField(tr("Reason (optional)"), text: $model.reason)
                    Button {
                        Task { await model.add() }
                    } label: {
                        Label(tr("Add"), systemImage: "plus")
                    }
                    .disabled(model.newSubject.trimmingCharacters(in: .whitespaces).isEmpty)
                    .accessibilityLabel(tr("Add to the list"))
                }
            }
        }
        .padding(.top, 8)
        .task { await model.refresh() }
    }
}
