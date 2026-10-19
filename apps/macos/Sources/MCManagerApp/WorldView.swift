import MCManagerKit
import SwiftUI

struct WorldView: View {
    @Bindable var model: WorldViewModel
    @State private var pending: DimensionItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(verbatim: tr("Total size") + ": " + model.totalSizeText).font(.headline)
                Spacer()
                IconButton(title: tr("Refresh"), symbol: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
            }
            TabStatusView(tab: model.tab)
            List(model.dimensions) { dimension in
                HStack {
                    Text(verbatim: dimensionLabel(dimension.id))
                    Spacer()
                    Text(verbatim: dimension.sizeText).monospacedDigit().foregroundStyle(.secondary)
                    Button(tr("Reset"), role: .destructive) { pending = dimension }
                        .disabled(!model.tab.canAct)
                        .accessibilityLabel(String(format: tr("Reset %@"), dimensionLabel(dimension.id)))
                }
            }
            .frame(minHeight: 80)
            Text(verbatim: tr("Pre-generation")).font(.headline)
            HStack {
                TextField(tr("Radius (blocks)"), text: $model.radiusText)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 160)
                TextField(tr("Center x,z (optional)"), text: $model.centerText)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 200)
                Button(tr("Start")) { Task { await model.startPregen() } }
                    .disabled(!model.tab.canAct)
                IconButton(title: tr("Refresh the pre-generation progress"), symbol: "arrow.clockwise") {
                    Task { await model.refreshPregen() }
                }
            }
            if !model.pregenText.isEmpty {
                Text(verbatim: model.pregenText).font(.system(.caption, design: .monospaced))
            }
        }
        .padding(.top, 8)
        .task { await model.refresh() }
        .alert(
            tr("Reset this dimension?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { dimension in
            Button(tr("Reset"), role: .destructive) {
                Task { await model.reset(dimension.id, confirmed: true) }
            }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { dimension in
            Text(verbatim: String(format: tr("%@ will be deleted and regenerated. This cannot be undone."), dimensionLabel(dimension.id)))
        }
    }
}
