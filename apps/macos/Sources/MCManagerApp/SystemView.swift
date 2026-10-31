import MCManagerKit
import SwiftUI

struct SystemView: View {
    let model: SystemViewModel
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(verbatim: tr("System")).font(.title2.bold())
                Spacer()
                Button(tr("Close"), action: close).keyboardShortcut(.cancelAction)
            }
            TabView {
                JavaPanel(model: model.java)
                    .tabItem { Label(tr("Java"), systemImage: "cup.and.saucer") }
                DevicesPanel(model: model.devices)
                    .tabItem { Label(tr("Devices"), systemImage: "iphone.and.laptop") }
                RouterPanel(model: model.router)
                    .tabItem { Label(tr("Router"), systemImage: "arrow.triangle.branch") }
                UpdatePanel(model: model.update)
                    .tabItem { Label(tr("Update"), systemImage: "arrow.down.circle") }
                DoctorPanel(model: model.doctor)
                    .tabItem { Label(tr("Diagnostics"), systemImage: "stethoscope") }
                NotificationsPanel(prefs: model.notifications)
                    .tabItem { Label(tr("Notifications"), systemImage: "bell") }
            }
        }
        .padding(20)
        .frame(width: 760, height: 580)
    }
}

struct JavaPanel: View {
    @Bindable var model: JavaViewModel
    @State private var pending: JavaRuntimeRow?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(verbatim: tr("The Java runtimes installed by MC Manager. Each server picks its own in its settings."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TabStatusView(tab: model.tab)
                GroupBox(tr("Installed")) {
                    VStack(alignment: .leading, spacing: 8) {
                        if model.rows.isEmpty {
                            Text(verbatim: tr("No Java installed by MC Manager")).foregroundStyle(.secondary)
                        }
                        ForEach(model.rows) { row in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(verbatim: "Java " + row.major)
                                    Text(verbatim: usage(row)).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if !model.tab.isReadOnly {
                                    IconButton(title: String(format: tr("Remove Java %@"), row.major), symbol: "trash",
                                               role: .destructive, enabled: !model.tab.isBusy) {
                                        pending = row
                                    }
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                if !model.tab.isReadOnly && !model.installable.isEmpty {
                    GroupBox(tr("Install a Java")) {
                        HStack {
                            Picker(tr("Version"), selection: $model.selectedMajor) {
                                ForEach(model.installable, id: \.self) { major in
                                    Text(verbatim: "Java " + major).tag(major)
                                }
                            }
                            .frame(maxWidth: 220)
                            Button(tr("Install")) { Task { await model.install(model.selectedMajor) } }
                                .disabled(!model.tab.canAct)
                        }
                    }
                }
            }
            .padding(.top, 8)
        }
        .task { await model.refresh() }
        .alert(
            tr("Remove this Java?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { row in
            Button(tr("Remove"), role: .destructive) { Task { await model.remove(row.major, confirmed: true) } }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { row in
            Text(verbatim: String(format: tr("Java %@ will be deleted. Servers that use it will not start until you pick another one."), row.major))
        }
    }

    private func usage(_ row: JavaRuntimeRow) -> String {
        row.servers.isEmpty
            ? tr("Used by no server")
            : String(format: tr("Used by %@"), row.servers.joined(separator: ", "))
    }
}

struct DevicesPanel: View {
    @Bindable var model: DevicesViewModel
    @State private var pending: DeviceRow?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                TabStatusView(tab: model.tab)
                if !model.tab.isDenied {
                    remoteBox
                    if !model.localOnlyDenied { pairingBox }
                    devicesBox
                    auditBox
                }
            }
            .padding(.top, 8)
        }
        .task { await model.refresh() }
        .alert(
            tr("Revoke this device?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { row in
            Button(tr("Revoke"), role: .destructive) { Task { await model.revoke(row.id, confirmed: true) } }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { row in
            Text(verbatim: String(format: tr("%@ loses access immediately and its open connections are closed."), row.name))
        }
    }

    private var remoteBox: some View {
        GroupBox(tr("Remote access")) {
            VStack(alignment: .leading, spacing: 8) {
                Text(verbatim: tr("Lets other devices drive this MC Manager over an encrypted connection."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if !model.localOnlyDenied {
                    Toggle(tr("Allow remote access"), isOn: Binding(
                        get: { model.remoteEnabled },
                        set: { value in Task { await model.setRemote(value) } }))
                        .disabled(!model.tab.canAct)
                }
                if !model.fingerprint.isEmpty {
                    Text(verbatim: tr("Certificate fingerprint")).font(.caption).foregroundStyle(.secondary)
                    Text(verbatim: model.fingerprint)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var pairingBox: some View {
        GroupBox(tr("Pair a device")) {
            VStack(alignment: .leading, spacing: 8) {
                Text(verbatim: tr("Generates a one-time code to type on the new device. It stays valid for a few minutes."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    TextField(tr("Device name (optional)"), text: $model.codeName)
                        .textFieldStyle(.roundedBorder)
                    Picker(tr("Role"), selection: $model.codeRole) {
                        ForEach(DevicesViewModel.roles, id: \.self) { role in
                            Text(verbatim: roleLabel(role)).tag(role)
                        }
                    }
                    .frame(maxWidth: 220)
                    Button(tr("Generate a code")) { Task { await model.newCode() } }
                        .disabled(!model.tab.canAct)
                }
                if let code = model.code {
                    Text(verbatim: code.code)
                        .font(.system(.title, design: .monospaced))
                        .textSelection(.enabled)
                        .accessibilityLabel(tr("Pairing code"))
                        .accessibilityValue(code.code)
                    Text(verbatim: String(format: tr("Valid for %d min"), code.minutes))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var devicesBox: some View {
        GroupBox(tr("Paired devices")) {
            VStack(alignment: .leading, spacing: 8) {
                if model.devices.isEmpty {
                    Text(verbatim: tr("No paired device")).foregroundStyle(.secondary)
                }
                ForEach(model.devices) { row in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(verbatim: row.name)
                            Text(verbatim: seen(row)).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if model.tab.isReadOnly {
                            Text(verbatim: roleLabel(row.role)).foregroundStyle(.secondary)
                        } else {
                            Picker(String(format: tr("Role of %@"), row.name), selection: Binding(
                                get: { row.role },
                                set: { value in Task { await model.setRole(row.id, role: value) } })) {
                                ForEach(DevicesViewModel.roles, id: \.self) { role in
                                    Text(verbatim: roleLabel(role)).tag(role)
                                }
                            }
                            .labelsHidden()
                            .frame(maxWidth: 160)
                            .accessibilityLabel(String(format: tr("Role of %@"), row.name))
                            IconButton(title: String(format: tr("Revoke %@"), row.name), symbol: "trash",
                                       role: .destructive, enabled: !model.tab.isBusy) {
                                pending = row
                            }
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var auditBox: some View {
        GroupBox(tr("Recent activity")) {
            VStack(alignment: .leading, spacing: 4) {
                if model.audit.isEmpty {
                    Text(verbatim: tr("No recorded activity")).foregroundStyle(.secondary)
                }
                ForEach(model.audit) { row in
                    Text(verbatim: line(row))
                        .font(.caption)
                        .foregroundStyle(row.ok ? Color.primary : Color.red)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func seen(_ row: DeviceRow) -> String {
        row.lastSeen.isEmpty ? tr("never connected") : String(format: tr("seen on %@"), row.lastSeen)
    }

    private func line(_ row: AuditRow) -> String {
        var parts = [row.at, row.action]
        if !row.device.isEmpty { parts.append(row.device) }
        if !row.server.isEmpty { parts.append(row.server) }
        if !row.ok { parts.append(tr("refused")) }
        return parts.joined(separator: " - ")
    }
}

struct RouterPanel: View {
    @Bindable var model: RouterViewModel
    @State private var pending: RouteRow?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(verbatim: tr("A single public port in front of several servers, routed by the host name players type."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TabStatusView(tab: model.tab)
                if !model.tab.isDenied {
                    GroupBox(tr("Router")) {
                        VStack(alignment: .leading, spacing: 8) {
                            Toggle(tr("Router enabled"), isOn: Binding(
                                get: { model.enabled },
                                set: { value in Task { await model.toggle(value) } }))
                                .disabled(!model.tab.canAct)
                            Picker(tr("Default server"), selection: Binding(
                                get: { model.defaultServer },
                                set: { value in Task { await model.setDefault(value) } })) {
                                Text(verbatim: "-").tag("")
                                ForEach(model.servers, id: \.self) { server in
                                    Text(verbatim: server).tag(server)
                                }
                            }
                            .frame(maxWidth: 360)
                            .disabled(!model.tab.canAct)
                            if !model.pending.isEmpty {
                                Label(tr("Restart required"), systemImage: "arrow.clockwise").foregroundStyle(.orange)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    routesBox
                    accessBox
                }
            }
            .padding(.top, 8)
        }
        .task { await model.refresh() }
        .alert(
            tr("Remove this route?"),
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            presenting: pending
        ) { row in
            Button(tr("Remove"), role: .destructive) { Task { await model.removeRoute(row.host, confirmed: true) } }
            Button(tr("Cancel"), role: .cancel) {}
        } message: { row in
            Text(verbatim: String(format: tr("Players using %@ will no longer reach their server."), row.host))
        }
    }

    private var routesBox: some View {
        GroupBox(tr("Routes")) {
            VStack(alignment: .leading, spacing: 8) {
                if model.routes.isEmpty {
                    Text(verbatim: tr("No route")).foregroundStyle(.secondary)
                }
                ForEach(model.routes) { row in
                    HStack {
                        Text(verbatim: row.host + " -> " + row.server)
                        Spacer()
                        if !model.tab.isReadOnly {
                            IconButton(title: String(format: tr("Remove the route %@"), row.host), symbol: "trash",
                                       role: .destructive, enabled: !model.tab.isBusy) {
                                pending = row
                            }
                        }
                    }
                }
                if !model.tab.isReadOnly {
                    HStack {
                        TextField(tr("Host name"), text: $model.newHost)
                            .textFieldStyle(.roundedBorder)
                        Picker(tr("Server"), selection: $model.newServer) {
                            ForEach(model.servers, id: \.self) { server in
                                Text(verbatim: server).tag(server)
                            }
                        }
                        .frame(maxWidth: 220)
                        Button(tr("Add the route")) { Task { await model.addRoute() } }
                            .disabled(!model.tab.canAct)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var accessBox: some View {
        GroupBox(tr("Access control")) {
            VStack(alignment: .leading, spacing: 8) {
                Text(verbatim: tr("Allowed and refused address ranges (CIDR).")).font(.caption).foregroundStyle(.secondary)
                accessList(tr("Allowed"), "allow", model.allow)
                accessList(tr("Refused"), "deny", model.deny)
                if !model.tab.isReadOnly {
                    HStack {
                        Picker(tr("List"), selection: $model.accessList) {
                            Text(verbatim: tr("Allowed")).tag("allow")
                            Text(verbatim: tr("Refused")).tag("deny")
                        }
                        .frame(maxWidth: 220)
                        TextField(tr("Address range, for example 10.0.0.0/8"), text: $model.newCidr)
                            .textFieldStyle(.roundedBorder)
                        Button(tr("Add the range")) {
                            Task { await model.editAccess(list: model.accessList, action: "add", cidr: model.newCidr) }
                        }
                        .disabled(!model.tab.canAct)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func accessList(_ title: String, _ list: String, _ values: [String]) -> some View {
        Text(verbatim: title).font(.headline)
        if values.isEmpty {
            Text(verbatim: "-").foregroundStyle(.secondary)
        }
        ForEach(values, id: \.self) { cidr in
            HStack {
                Text(verbatim: cidr)
                Spacer()
                if !model.tab.isReadOnly {
                    IconButton(title: String(format: tr("Remove %@"), cidr), symbol: "minus.circle",
                               enabled: !model.tab.isBusy) {
                        Task { await model.editAccess(list: list, action: "remove", cidr: cidr) }
                    }
                }
            }
        }
    }
}

struct UpdatePanel: View {
    @Bindable var model: UpdateViewModel
    @State private var confirmApply = false
    @State private var confirmRollback = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(verbatim: tr("Updates are checked by signature and checksum. The service then restarts."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TabStatusView(tab: model.tab)
                if !model.tab.isDenied {
                    GroupBox(tr("Version")) {
                        VStack(alignment: .leading, spacing: 8) {
                            if model.loaded {
                                Text(verbatim: model.available
                                    ? String(format: tr("Version %@, %@ is available"), model.current, model.latest)
                                    : String(format: tr("Version %@, up to date"), model.current))
                            }
                            HStack {
                                Button(tr("Check again")) { Task { await model.refresh() } }
                                    .disabled(model.tab.isBusy)
                                if !model.tab.isReadOnly {
                                    Button(tr("Install the update")) { confirmApply = true }
                                        .disabled(!model.tab.canAct || !model.available)
                                        .alert(tr("Install the update?"), isPresented: $confirmApply) {
                                            Button(tr("Install")) { Task { await model.apply(confirmed: true) } }
                                            Button(tr("Cancel"), role: .cancel) {}
                                        } message: {
                                            Text(verbatim: String(format: tr("Version %@ will be installed and MC Manager will restart. Running servers are not stopped."), model.latest))
                                        }
                                    Button(tr("Go back to the previous version")) { confirmRollback = true }
                                        .disabled(!model.tab.canAct || !model.rollbackAvailable)
                                        .alert(tr("Go back?"), isPresented: $confirmRollback) {
                                            Button(tr("Restore"), role: .destructive) {
                                                Task { await model.rollback(confirmed: true) }
                                            }
                                            Button(tr("Cancel"), role: .cancel) {}
                                        } message: {
                                            Text(verbatim: tr("The previous version of MC Manager will be restored."))
                                        }
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .padding(.top, 8)
        }
        .task { await model.refresh() }
    }
}

struct DoctorPanel: View {
    @Bindable var model: DoctorViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(verbatim: tr("Checks the machine and every server, with the fix to apply when something is wrong."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                TabStatusView(tab: model.tab)
                HStack {
                    Button(tr("Run the diagnostics")) { Task { await model.run() } }
                        .disabled(model.tab.isBusy)
                    if model.tab.isBusy { ProgressView().controlSize(.small) }
                }
                if model.hasRun {
                    Text(verbatim: summary).font(.headline)
                    ForEach(model.checks) { check in
                        VStack(alignment: .leading, spacing: 2) {
                            Label(title(check), systemImage: symbol(check.level))
                                .foregroundStyle(color(check.level))
                            if !check.detail.isEmpty {
                                Text(verbatim: check.detail).font(.caption).foregroundStyle(.secondary)
                            }
                            if !check.fix.isEmpty {
                                Text(verbatim: String(format: tr("Fix: %@"), check.fix)).font(.caption)
                            }
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
            }
            .padding(.top, 8)
        }
    }

    private var summary: String {
        if model.errorCount > 0 { return String(format: tr("%d error(s) to fix"), model.errorCount) }
        if model.warningCount > 0 { return String(format: tr("%d warning(s)"), model.warningCount) }
        return tr("Nothing to report")
    }

    private func title(_ check: CheckRow) -> String {
        check.server.isEmpty ? check.name : check.server + ": " + check.name
    }

    private func symbol(_ level: String) -> String {
        switch level {
        case "ok": return "checkmark.circle"
        case "warn": return "exclamationmark.triangle"
        default: return "xmark.octagon"
        }
    }

    private func color(_ level: String) -> Color {
        switch level {
        case "ok": return .green
        case "warn": return .orange
        default: return .red
        }
    }
}

struct NotificationsPanel: View {
    let prefs: NotificationPrefs

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(verbatim: tr("System notifications when the window is in the background."))
                .font(.caption)
                .foregroundStyle(.secondary)
            ForEach(NotificationPrefs.kinds, id: \.self) { kind in
                Toggle(notificationPrefLabel(kind), isOn: Binding(
                    get: { prefs.isEnabled(kind) },
                    set: { prefs.set(kind, $0) }))
            }
            Spacer()
        }
        .padding(.top, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
