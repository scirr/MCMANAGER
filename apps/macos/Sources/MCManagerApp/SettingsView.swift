import MCManagerKit
import SwiftUI

struct SettingsView: View {
    @Bindable var model: SettingsViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                TabStatusView(tab: model.tab)

                GroupBox(tr("Mode")) {
                    Picker(tr("Mode"), selection: Binding(
                        get: { model.mode },
                        set: { value in Task { await model.setMode(value) } }
                    )) {
                        ForEach(SettingsViewModel.modes, id: \.self) { mode in
                            Text(verbatim: modeLabel(mode)).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .disabled(!model.tab.canAct)
                    .accessibilityLabel(tr("Mode"))
                }

                GroupBox(tr("Opening hours")) {
                    HStack {
                        TextField(tr("Opens (HH:MM)"), text: $model.openTime)
                        TextField(tr("Closes (HH:MM)"), text: $model.closeTime)
                        Button(tr("Save")) { Task { await model.saveSchedule() } }
                            .disabled(!model.tab.canAct)
                    }
                    .textFieldStyle(.roundedBorder)
                }

                GroupBox(tr("Java")) {
                    HStack {
                        Picker(tr("Java"), selection: $model.javaChoice) {
                            ForEach(model.javaChoices, id: \.self) { choice in
                                Text(verbatim: javaChoiceLabel(choice)).tag(choice)
                            }
                        }
                        .labelsHidden()
                        .accessibilityLabel(tr("Java"))
                        Button(tr("Save")) { Task { await model.saveJava() } }
                            .disabled(!model.tab.canAct)
                    }
                }

                GroupBox(tr("Server settings")) {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(model.items, id: \.key) { item in
                            SettingRow(item: item)
                        }
                        HStack {
                            Spacer()
                            Button(tr("Save")) { Task { await model.save() } }
                                .disabled(!model.tab.canAct || !model.items.contains { $0.isChanged })
                        }
                    }
                }
            }
            .padding(.top, 8)
        }
        .task { await model.refresh() }
    }
}

struct SettingRow: View {
    @Bindable var item: SettingItem

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(verbatim: settingLabel(item.key))
                if item.isSecret {
                    Text(verbatim: item.isSet ? tr("configured (hidden, type to replace)") : tr("not set"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(minWidth: 220, alignment: .leading)
            if item.isSecret {
                SecureField(settingLabel(item.key), text: $item.value)
                    .textFieldStyle(.roundedBorder)
            } else {
                TextField(settingLabel(item.key), text: $item.value)
                    .textFieldStyle(.roundedBorder)
            }
        }
        .accessibilityElement(children: .contain)
    }
}
