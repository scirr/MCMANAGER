import MCManagerKit
import SwiftUI

struct BackupsView: View {
    let model: BackupsViewModel
    @State private var pending: BackupItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button {
                    Task { await model.create() }
                } label: {
                    Label(tr("Back up now"), systemImage: "externaldrive.badge.plus")
                }
                .disabled(!model.tab.canAct)
                Spacer()
                IconButton(title: tr("Refresh"), symbol: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
            }
            TabStatusView(tab: model.tab)
            List(model.items) { item in
                HStack {
                    VStack(alignment: .leading) {
                        Text(verbatim: item.date)
                        Text(verbatim: originLabel(item.origin) + (item.encrypted ? " - " + tr("encrypted") : ""))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(verbatim: item.sizeText).monospacedDigit().foregroundStyle(.secondary)
                    if !model.tab.isReadOnly {
                        Button(tr("Restore")) { pending = item }
                            .disabled(model.tab.isBusy)
                            .accessibilityLabel(String(format: tr("Restore the backup of %@"), item.date))
                    }
                }
            }
            .overlay {
                if model.isEmpty { ContentUnavailableView(tr("No backups"), systemImage: "externaldrive") }
            }
        }
        .padding(.top, 8)
        .task { await model.refresh() }
        .alert(
            tr("Restore this backup?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { item in
            Button(tr("Restore"), role: .destructive) {
                Task { await model.restore(item.id, confirmed: true) }
            }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { item in
            Text(verbatim: String(format: tr("The server will be stopped and the current world replaced by the backup of %@. A safety copy is kept first."), item.date))
        }
    }
}
