import MCManagerKit
import SwiftUI

struct AlertsView: View {
    @Bindable var model: AlertsViewModel
    @State private var pending: AlertRow?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(verbatim: tr("Messages sent when something happens to this server."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TabStatusView(tab: model.tab)
                GroupBox(tr("Channels")) {
                    VStack(alignment: .leading, spacing: 8) {
                        if model.isEmpty {
                            Text(verbatim: tr("No alert channel")).foregroundStyle(.secondary)
                        }
                        ForEach(model.rows) { row in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(verbatim: row.name)
                                    Text(verbatim: details(row)).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if !model.tab.isReadOnly && !row.legacy {
                                    Button(tr("Test")) { Task { await model.test(row.name) } }
                                        .accessibilityLabel(String(format: tr("Send a test to %@"), row.name))
                                        .disabled(model.tab.isBusy)
                                    IconButton(title: String(format: tr("Remove the channel %@"), row.name),
                                               symbol: "trash", role: .destructive, enabled: !model.tab.isBusy) {
                                        pending = row
                                    }
                                }
                            }
                        }
                        if !model.tab.isReadOnly && !model.isEmpty {
                            Button(tr("Send a test to every channel")) { Task { await model.test(nil) } }
                                .disabled(model.tab.isBusy)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                if !model.tab.isReadOnly {
                    form
                }
            }
            .padding(.top, 8)
        }
        .task { await model.refresh() }
        .alert(
            tr("Remove this channel?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { row in
            Button(tr("Remove"), role: .destructive) { Task { await model.remove(row.name, confirmed: true) } }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { row in
            Text(verbatim: String(format: tr("The channel %@ will no longer receive alerts."), row.name))
        }
    }

    private var form: some View {
        GroupBox(tr("Add a channel")) {
            VStack(alignment: .leading, spacing: 8) {
                Picker(tr("Type"), selection: $model.newType) {
                    ForEach(AlertsViewModel.types, id: \.self) { type in
                        Text(verbatim: alertTypeLabel(type)).tag(type)
                    }
                }
                .frame(maxWidth: 300)
                TextField(tr("Channel name (optional)"), text: $model.channelName)
                ForEach(model.fields, id: \.key) { field in
                    let binding = Binding(
                        get: { model.values[field.key] ?? "" },
                        set: { model.values[field.key] = $0 })
                    if field.secret {
                        SecureField(alertFieldLabel(field.key), text: binding)
                    } else {
                        TextField(alertFieldLabel(field.key), text: binding)
                    }
                }
                Text(verbatim: tr("Events")).font(.headline)
                Text(verbatim: tr("No choice means every event.")).font(.caption).foregroundStyle(.secondary)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 170), alignment: .leading)], alignment: .leading) {
                    ForEach(AlertsViewModel.events, id: \.self) { event in
                        Toggle(alertEventLabel(event), isOn: Binding(
                            get: { model.selectedEvents.contains(event) },
                            set: { on in
                                if on { model.selectedEvents.insert(event) } else { model.selectedEvents.remove(event) }
                            }))
                    }
                }
                Button(tr("Add the channel")) { Task { await model.add() } }
                    .disabled(!model.tab.canAct)
            }
            .textFieldStyle(.roundedBorder)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func details(_ row: AlertRow) -> String {
        var parts = [alertTypeLabel(row.type)]
        if !row.target.isEmpty { parts.append(row.target) }
        parts.append(row.events.map { $0 == "*" ? tr("every event") : alertEventLabel($0) }.joined(separator: ", "))
        if row.legacy { parts.append(tr("announcement channel, read-only")) }
        return parts.joined(separator: " - ")
    }
}
