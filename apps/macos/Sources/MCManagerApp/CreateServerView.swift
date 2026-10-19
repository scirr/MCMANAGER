import MCManagerKit
import SwiftUI

struct CreateServerView: View {
    @Bindable var model: CreateServerViewModel
    let finished: (String) -> Void
    let cancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(verbatim: tr("New server")).font(.title2.bold())
            Text(verbatim: stepTitle).foregroundStyle(.secondary)
            Group {
                switch model.step {
                case 0: identityStep
                case 1: resourcesStep
                default: summaryStep
                }
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            TabStatusView(tab: model.tab)
            HStack {
                Button(tr("Cancel"), role: .cancel, action: cancel)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button(tr("Previous")) { model.back() }
                    .disabled(!model.canBack)
                if model.canNext {
                    Button(tr("Next")) { model.next() }
                        .keyboardShortcut(.defaultAction)
                } else {
                    Button(tr("Create the server")) { Task { await model.create() } }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!model.canCreate)
                }
            }
        }
        .padding(20)
        .frame(width: 520, height: 420)
        .onChange(of: model.createdName) {
            if !model.createdName.isEmpty { finished(model.createdName) }
        }
    }

    private var stepTitle: String {
        switch model.step {
        case 0: return tr("Step 1 of 3: name and software")
        case 1: return tr("Step 2 of 3: resources")
        default: return tr("Step 3 of 3: summary and EULA")
        }
    }

    private var identityStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField(tr("Server name"), text: $model.name)
            Picker(tr("Server software"), selection: $model.loader) {
                ForEach(CreateServerViewModel.loaders, id: \.self) { loader in
                    Text(verbatim: loader).tag(loader)
                }
            }
            if !model.isProxy {
                TextField(tr("Minecraft version (empty: latest)"), text: $model.version)
            }
        }
        .textFieldStyle(.roundedBorder)
    }

    private var resourcesStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField(tr("Memory (e.g. 4G)"), text: $model.ram)
            TextField(tr("Port (empty: automatic)"), text: $model.port)
            TextField(tr("RCON port (empty: automatic)"), text: $model.rconPort)
        }
        .textFieldStyle(.roundedBorder)
    }

    private var summaryStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(verbatim: model.name.trimmingCharacters(in: .whitespaces) + " - " + model.loader
                + (model.version.isEmpty || model.isProxy ? "" : " " + model.version)
                + " - " + model.ram.uppercased())
                .font(.headline)
            Text(verbatim: tr("Creating the server downloads its files. You must accept the Minecraft EULA (https://aka.ms/MinecraftEULA)."))
            Toggle(tr("I accept the Minecraft EULA"), isOn: $model.acceptEula)
        }
    }
}
