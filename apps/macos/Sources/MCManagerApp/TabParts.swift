import MCManagerKit
import SwiftUI

struct TabStatusView: View {
    let tab: TabRunner

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if tab.isBusy {
                ProgressView(value: tab.progress, total: 100)
                    .accessibilityLabel(tr("Operation in progress"))
            }
            if tab.isDenied {
                Label(tr("This device is not allowed to see this."), systemImage: "lock")
                    .foregroundStyle(.secondary)
            } else if tab.isReadOnly {
                Label(tr("This device is not allowed to change this."), systemImage: "lock")
                    .foregroundStyle(.secondary)
            }
            if let done = doneLabel(tab.lastDone) {
                Label(done, systemImage: "checkmark.circle")
                    .foregroundStyle(.green)
            }
            if tab.restartRequired {
                Label(tr("Restart the server to apply the changes."), systemImage: "arrow.clockwise")
                    .foregroundStyle(.orange)
            }
        }
    }
}

struct IconButton: View {
    let title: String
    let symbol: String
    var role: ButtonRole?
    var enabled = true
    let action: () -> Void

    var body: some View {
        Button(role: role, action: action) {
            Label(title, systemImage: symbol)
        }
        .labelStyle(.iconOnly)
        .disabled(!enabled)
        .help(title)
        .accessibilityLabel(title)
    }
}
