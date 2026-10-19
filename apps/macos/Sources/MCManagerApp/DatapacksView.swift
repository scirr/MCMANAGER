import MCManagerKit
import SwiftUI

struct DatapacksView: View {
    let model: DatapacksViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Spacer()
                IconButton(title: tr("Refresh"), symbol: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
            }
            TabStatusView(tab: model.tab)
            List(model.items) { item in
                HStack {
                    VStack(alignment: .leading) {
                        Text(verbatim: item.packId)
                        Text(verbatim: status(item)).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button(item.enabled ? tr("Disable") : tr("Enable")) {
                        Task { await model.setEnabled(item.file, enabled: !item.enabled) }
                    }
                    .disabled(!item.canToggle || !model.tab.canAct)
                    .accessibilityLabel((item.enabled ? tr("Disable") : tr("Enable")) + " " + item.packId)
                }
            }
            .overlay {
                if model.isEmpty { ContentUnavailableView(tr("No datapack found."), systemImage: "shippingbox") }
            }
        }
        .padding(.top, 8)
        .task { await model.refresh() }
    }

    private func status(_ item: DatapackItem) -> String {
        if let problem = item.problem { return datapackProblemLabel(problem) }
        return item.enabled ? tr("enabled") : tr("disabled")
    }
}
