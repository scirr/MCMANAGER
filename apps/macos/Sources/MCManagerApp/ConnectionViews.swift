import MCManagerKit
import SwiftUI

struct PairingView: View {
    @Bindable var model: PairingWizardViewModel
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(verbatim: tr("Add a remote MC Manager")).font(.title2.bold())
            Text(verbatim: prompt)
            content
            if !model.errorCode.isEmpty {
                Text(verbatim: message(for: ApiError(code: model.errorCode)))
                    .foregroundStyle(.red)
            }
            if model.isBusy { ProgressView().controlSize(.small) }
            HStack {
                Button(model.step == .done ? tr("Close") : tr("Cancel"), role: .cancel, action: close)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                actions
            }
        }
        .padding(20)
        .frame(width: 520)
    }

    private var prompt: String {
        switch model.step {
        case .address: return tr("Address of the remote MC Manager (host:port)")
        case .confirm: return tr("Compare this SHA-256 fingerprint with the one shown on the server (mc remote status). Continue only if they are identical.")
        case .code: return tr("Pairing code (8 digits) generated on the server")
        case .name: return tr("Name of this device")
        case .done: return tr("Paired.")
        }
    }

    @ViewBuilder private var content: some View {
        switch model.step {
        case .address:
            TextField(tr("host:port"), text: $model.address)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await model.probe() } }
        case .confirm:
            Text(verbatim: model.fingerprint)
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
        case .code:
            TextField(tr("Pairing code"), text: $model.code)
                .textFieldStyle(.roundedBorder)
                .onSubmit { model.submitCode() }
        case .name:
            TextField(tr("Device name"), text: $model.deviceName)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await model.finish() } }
        case .done:
            EmptyView()
        }
    }

    @ViewBuilder private var actions: some View {
        switch model.step {
        case .address:
            Button(tr("Next")) { Task { await model.probe() } }
                .keyboardShortcut(.defaultAction)
                .disabled(model.isBusy)
        case .confirm:
            Button(tr("Reject"), role: .destructive) { model.reject() }
            Button(tr("Trust this fingerprint")) { model.confirmFingerprint() }
                .keyboardShortcut(.defaultAction)
        case .code:
            Button(tr("Next")) { model.submitCode() }
                .keyboardShortcut(.defaultAction)
        case .name:
            Button(tr("Pair")) { Task { await model.finish() } }
                .keyboardShortcut(.defaultAction)
                .disabled(model.isBusy)
        case .done:
            EmptyView()
        }
    }
}
