import Foundation
import Observation

public struct JavaRuntimeRow: Equatable, Identifiable, Sendable {
    public let major: String
    public let path: String
    public let servers: [String]
    public var id: String { major }
}

@MainActor
@Observable
public final class JavaViewModel {
    public static let majors = ["8", "11", "17", "21", "25"]

    public private(set) var rows: [JavaRuntimeRow] = []
    public var selectedMajor = "21"
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        self.errors = errors
        tab = TabRunner(client: client, errors: errors, server: "")
    }

    public var installable: [String] {
        let installed = Set(rows.map(\.major))
        return Self.majors.filter { !installed.contains($0) }
    }

    public func refresh() async {
        await tab.read {
            let document = try await client.javaRuntimes()
            var used: [String: [String]] = [:]
            for entry in document.servers {
                used[entry.java?.text ?? "", default: []].append(entry.server)
            }
            rows = document.runtimes.keys
                .sorted { ($0.count, $0) < ($1.count, $1) }
                .map { JavaRuntimeRow(major: $0, path: document.runtimes[$0] ?? "", servers: used[$0] ?? []) }
            if !installable.contains(selectedMajor), let first = installable.first { selectedMajor = first }
        }
    }

    public func install(_ major: String) async {
        guard let number = Int(major), number >= 8 else {
            errors.show("java_unknown_version")
            return
        }
        if await tab.runJob("java_installed", { try await self.client.installJava(major: number) }) {
            await refresh()
        }
    }

    public func remove(_ major: String?, confirmed: Bool) async {
        guard confirmed, let major, let number = Int(major) else { return }
        if await tab.write({ _ = try await self.client.removeJava(major: number) }) {
            tab.markDone("java_removed")
            await refresh()
        }
    }
}

public struct DeviceRow: Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let role: String
    public let servers: [String]
    public let lastSeen: String
    public let lastIp: String
}

public struct AuditRow: Equatable, Identifiable, Sendable {
    public let id: Int
    public let at: String
    public let action: String
    public let device: String
    public let server: String
    public let ok: Bool
    public let result: String
}

public struct PairingCodeInfo: Equatable, Sendable {
    public let code: String
    public let minutes: Int
}

@MainActor
@Observable
public final class DevicesViewModel {
    public static let roles = ["viewer", "operator", "admin"]

    public private(set) var devices: [DeviceRow] = []
    public private(set) var audit: [AuditRow] = []
    public private(set) var remoteEnabled = false
    public private(set) var bind = ""
    public private(set) var fingerprint = ""
    public private(set) var code: PairingCodeInfo?
    public private(set) var localOnlyDenied = false
    public var codeName = ""
    public var codeRole = "operator"
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        self.errors = errors
        tab = TabRunner(client: client, errors: errors, server: "")
    }

    public func refresh() async {
        let listed = await tab.read {
            let list = try await client.listDevices()
            devices = list.devices.filter { $0.revoked != true }.map { device in
                DeviceRow(id: device.id, name: device.name ?? device.id,
                          role: device.roles?.defaultRole ?? "viewer", servers: device.servers ?? [],
                          lastSeen: TabRunner.stamp(device.lastSeen), lastIp: device.lastIp ?? "")
            }
        }
        guard listed else { return }
        await tab.read {
            let status = try await client.remoteStatus()
            remoteEnabled = status.enabled ?? false
            bind = status.bind ?? ""
            fingerprint = status.fingerprint ?? ""
        }
        await tab.read {
            let log = try await client.auditLog(limit: 50)
            audit = log.entries.enumerated().map { index, entry in
                AuditRow(id: index, at: TabRunner.stamp(entry.at), action: entry.action ?? "",
                         device: entry.device ?? "", server: entry.server ?? "", ok: entry.ok ?? false,
                         result: entry.result ?? "")
            }
        }
    }

    private func local(_ work: () async throws -> Void) async -> Bool {
        do {
            try await work()
            return true
        } catch let error as ApiError where error.status == 403 {
            localOnlyDenied = true
            errors.report(error)
            return false
        } catch {
            errors.report(error)
            return false
        }
    }

    public func setRemote(_ enabled: Bool) async {
        guard enabled != remoteEnabled else { return }
        if await local({ _ = try await self.client.setRemoteAccess(enabled: enabled) }) {
            tab.markDone(enabled ? "remote_enabled" : "remote_disabled")
            await refresh()
        }
    }

    public func newCode() async {
        guard Self.roles.contains(codeRole) else { return }
        code = nil
        let name = codeName.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
        let role = codeRole
        _ = await local {
            let document = try await self.client.createPairingCode(name: name, role: role)
            self.code = PairingCodeInfo(code: document.pairingCode ?? "",
                                        minutes: max(1, (document.expiresInS ?? 0) / 60))
            self.tab.markDone("code_ready")
        }
    }

    public func setRole(_ device: String, role: String) async {
        guard Self.roles.contains(role) else { return }
        if await tab.write({ _ = try await self.client.setDeviceRole(device, role: role) }) {
            tab.markDone("role_saved")
            await refresh()
        }
    }

    public func revoke(_ device: String?, confirmed: Bool) async {
        guard confirmed, let device, !device.isEmpty else { return }
        if await tab.write({ _ = try await self.client.revokeDevice(device) }) {
            tab.markDone("device_revoked")
            await refresh()
        }
    }
}

@MainActor
@Observable
public final class UpdateViewModel {
    public private(set) var current = ""
    public private(set) var latest = ""
    public private(set) var available = false
    public private(set) var rollbackAvailable = false
    public private(set) var loaded = false
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        tab = TabRunner(client: client, errors: errors, server: "")
    }

    public func refresh() async {
        await tab.read {
            let check = try await client.checkUpdate()
            current = check.current ?? ""
            latest = check.latest ?? ""
            available = check.updateAvailable ?? false
            rollbackAvailable = check.rollbackAvailable ?? false
            loaded = true
        }
    }

    public func apply(confirmed: Bool) async {
        guard confirmed, available else { return }
        if await tab.runJob("update_done", { try await self.client.applyUpdate() }) {
            await refresh()
        }
    }

    public func rollback(confirmed: Bool) async {
        guard confirmed, rollbackAvailable else { return }
        if await tab.write({ _ = try await self.client.rollbackUpdate() }) {
            tab.markDone("update_rolled_back")
            await refresh()
        }
    }
}

public struct CheckRow: Equatable, Identifiable, Sendable {
    public let id: Int
    public let server: String
    public let name: String
    public let level: String
    public let detail: String
    public let fix: String
}

@MainActor
@Observable
public final class DoctorViewModel {
    public private(set) var checks: [CheckRow] = []
    public private(set) var errorCount = 0
    public private(set) var warningCount = 0
    public private(set) var hasRun = false
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        tab = TabRunner(client: client, errors: errors, server: "")
    }

    public var summary: String {
        if errorCount > 0 { return "errors" }
        return warningCount > 0 ? "warnings" : "clean"
    }

    public func run() async {
        if tab.isBusy { return }
        tab.setBusy(true)
        defer { tab.setBusy(false) }
        await tab.read {
            let report = try await client.doctor(server: nil)
            checks = report.checks.enumerated().map { index, check in
                CheckRow(id: index, server: check.server ?? "", name: check.name ?? "",
                         level: check.level ?? (check.ok == true ? "ok" : "err"),
                         detail: check.detail ?? "", fix: check.fix ?? "")
            }
            errorCount = report.errors ?? 0
            warningCount = report.warnings ?? 0
            hasRun = true
        }
    }
}

public struct RouteRow: Equatable, Identifiable, Sendable {
    public let host: String
    public let server: String
    public var id: String { host }
}

@MainActor
@Observable
public final class RouterViewModel {
    public private(set) var enabled = false
    public private(set) var port: Int?
    public private(set) var defaultServer = ""
    public private(set) var routes: [RouteRow] = []
    public private(set) var allow: [String] = []
    public private(set) var deny: [String] = []
    public private(set) var pending: [String] = []
    public private(set) var servers: [String] = []
    public var newHost = ""
    public var newServer = ""
    public var accessList = "allow"
    public var newCidr = ""
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        self.errors = errors
        tab = TabRunner(client: client, errors: errors, server: "")
    }

    private func apply(_ status: RouterStatus) {
        let config = status.config
        enabled = config?.enabled ?? false
        port = config?.port
        defaultServer = config?.defaultServer ?? ""
        routes = (config?.routes ?? [:]).sorted { $0.key < $1.key }.map { RouteRow(host: $0.key, server: $0.value) }
        allow = config?.allow ?? []
        deny = config?.deny ?? []
        pending = status.pendingRestart ?? []
    }

    public func refresh() async {
        let loaded = await tab.read { apply(try await client.router()) }
        guard loaded else { return }
        await tab.read {
            servers = try await client.listServers().map(\.name)
            if newServer.isEmpty || !servers.contains(newServer) { newServer = servers.first ?? "" }
        }
    }

    private func change(_ kind: String, _ work: () async throws -> RouterStatus) async {
        var status: RouterStatus?
        if await tab.write({ status = try await work() }), let status {
            apply(status)
            tab.markDone(kind)
        }
    }

    public func toggle(_ value: Bool) async {
        guard value != enabled else { return }
        if value {
            await change("router_enabled") { try await self.client.enableRouter() }
        } else {
            await change("router_disabled") { try await self.client.disableRouter() }
        }
    }

    public func addRoute() async {
        let host = newHost.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let server = newServer
        guard !host.isEmpty, servers.contains(server) else {
            errors.show("invalid_value")
            return
        }
        await change("route_saved") { try await self.client.setRouterRoute(host: host, server: server) }
        if tab.lastDone == "route_saved" { newHost = "" }
    }

    public func removeRoute(_ host: String?, confirmed: Bool) async {
        guard confirmed, let host, !host.isEmpty else { return }
        await change("route_removed") { try await self.client.removeRouterRoute(host: host) }
    }

    public func setDefault(_ server: String) async {
        guard servers.contains(server), server != defaultServer else { return }
        await change("router_default_saved") { try await self.client.setRouterDefault(server: server) }
    }

    public func editAccess(list: String, action: String, cidr: String) async {
        let range = cidr.trimmingCharacters(in: .whitespacesAndNewlines)
        guard ["allow", "deny"].contains(list), ["add", "remove"].contains(action), !range.isEmpty else { return }
        await change("router_access_saved") {
            try await self.client.editRouterAccess(list: list, action: action, cidr: range)
        }
        if action == "add" && tab.lastDone == "router_access_saved" { newCidr = "" }
    }
}

@MainActor
public final class SystemViewModel {
    public let java: JavaViewModel
    public let devices: DevicesViewModel
    public let router: RouterViewModel
    public let update: UpdateViewModel
    public let doctor: DoctorViewModel
    public let notifications: NotificationPrefs

    public init(client: McClientProtocol, errors: ErrorReporter, notifications: NotificationPrefs) {
        java = JavaViewModel(client: client, errors: errors)
        devices = DevicesViewModel(client: client, errors: errors)
        router = RouterViewModel(client: client, errors: errors)
        update = UpdateViewModel(client: client, errors: errors)
        doctor = DoctorViewModel(client: client, errors: errors)
        self.notifications = notifications
    }
}
