import MCManagerKit
import SwiftUI

struct TasksView: View {
    @Bindable var model: TasksViewModel
    @State private var pending: TaskItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                TextField(tr("Name (optional)"), text: $model.newName)
                TextField(tr("Schedule (cron)"), text: $model.newCron)
                Picker(tr("Action"), selection: $model.newAction) {
                    ForEach(TasksViewModel.actions, id: \.self) { action in
                        Text(verbatim: taskActionLabel(action)).tag(action)
                    }
                }
                .frame(maxWidth: 170)
            }
            .textFieldStyle(.roundedBorder)
            HStack {
                if model.needsCommand {
                    TextField(tr("Console command"), text: $model.newCommand)
                        .textFieldStyle(.roundedBorder)
                }
                if model.allowsWarn {
                    TextField(tr("Warnings, e.g. 5m,1m"), text: $model.newWarn)
                        .textFieldStyle(.roundedBorder)
                }
                Button {
                    Task { await model.create() }
                } label: {
                    Label(tr("Add task"), systemImage: "plus")
                }
                .disabled(!model.tab.canAct)
                IconButton(title: tr("Refresh"), symbol: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
            }
            TabStatusView(tab: model.tab)
            List(model.items) { item in
                HStack {
                    if !model.tab.isReadOnly {
                        Toggle(isOn: Binding(
                            get: { item.enabled },
                            set: { value in Task { await model.setEnabled(item.id, enabled: value) } }
                        )) {
                            EmptyView()
                        }
                        .labelsHidden()
                        .disabled(model.tab.isBusy)
                        .accessibilityLabel(String(format: tr("Enable the task %@"), title(item)))
                    }
                    VStack(alignment: .leading) {
                        Text(verbatim: title(item))
                        Text(verbatim: details(item)).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if !model.tab.isReadOnly {
                        Button(tr("Run now")) { Task { await model.run(item.id) } }
                            .disabled(model.tab.isBusy)
                        IconButton(title: String(format: tr("Delete the task %@"), title(item)), symbol: "trash",
                                   role: .destructive, enabled: !model.tab.isBusy) {
                            pending = item
                        }
                    }
                }
            }
            .overlay {
                if model.isEmpty { ContentUnavailableView(tr("No scheduled task."), systemImage: "calendar.badge.clock") }
            }
        }
        .padding(.top, 8)
        .task { await model.refresh() }
        .alert(
            tr("Delete this task?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { item in
            Button(tr("Delete"), role: .destructive) {
                Task { await model.delete(item.id, confirmed: true) }
            }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { item in
            Text(verbatim: String(format: tr("The task %@ will be deleted."), title(item)))
        }
    }

    private func title(_ item: TaskItem) -> String {
        item.name.isEmpty ? taskActionLabel(item.kind) + " #\(item.id)" : item.name
    }

    private func details(_ item: TaskItem) -> String {
        var parts = [taskActionLabel(item.kind), item.cron]
        if !item.command.isEmpty { parts.append(item.command) }
        if !item.warnText.isEmpty { parts.append(item.warnText) }
        if !item.nextRun.isEmpty { parts.append(String(format: tr("next: %@"), item.nextRun)) }
        let last = lastResultLabel(item.lastResult)
        if !last.isEmpty { parts.append(last) }
        return parts.joined(separator: " - ")
    }
}
