import Foundation
import Observation

@MainActor
@Observable
public final class SettingItem {
    public let key: String
    public let isSecret: Bool
    public let isSet: Bool
    public let original: String
    public var value: String

    public init(key: String, isSecret: Bool, isSet: Bool, original: String) {
        self.key = key
        self.isSecret = isSecret
        self.isSet = isSet
        self.original = original
        value = original
    }

    public var isChanged: Bool {
        isSecret ? !value.isEmpty : value.trimmingCharacters(in: .whitespacesAndNewlines) != original
    }
}

@MainActor
@Observable
public final class SettingsViewModel {
    public static let keys = [
        "nom_serveur", "port", "rcon_port", "ram_allocation", "cpu_affinity", "jar_name", "domaine",
        "dossier_backup", "backup_retention_days", "backup_keep", "stop_timeout",
        "internal_port", "metrics_bind", "metrics_allow_remote",
        "sleep_hold_timeout", "sleep_proxy_protocol",
        "mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file",
    ]
    public static let secretKeys = [
        "mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file", "alerts", "backup_remotes",
    ]
    public static let modes = ["schedule", "always-on", "maintenance"]
    public static let joinModes = ["kick", "hold"]
    public static let sleepMinimumMinutes = 5
    public static let systemJava = "system"

    public private(set) var items: [SettingItem] = []
    public private(set) var javaChoices: [String] = []
    public private(set) var mode = ""
    public var openTime = ""
    public var closeTime = ""
    public var javaChoice = ""
    public var sleepEnabled = false
    public var sleepMinutes = ""
    public var sleepJoinMode = "kick"
    public var sleepFreeze = false
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter
    @ObservationIgnored private let server: String
    @ObservationIgnored private var loadedJava = ""
    @ObservationIgnored private var loadedSleep = SleepSettings(enabled: false, afterS: 0)

    public init(client: McClientProtocol, errors: ErrorReporter, server: String) {
        self.client = client
        self.errors = errors
        self.server = server
        tab = TabRunner(client: client, errors: errors, server: server)
    }

    public static func clock(_ hour: Int, _ minute: Int) -> String {
        String(format: "%02d:%02d", hour, minute)
    }

    public static func parseClock(_ text: String) -> (hour: Int, minute: Int)? {
        let parts = text.trimmingCharacters(in: .whitespaces).split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              parts[0].allSatisfy(\.isNumber), parts[1].allSatisfy(\.isNumber),
              let hour = Int(parts[0]), let minute = Int(parts[1]),
              (0...23).contains(hour), (0...59).contains(minute) else { return nil }
        return (hour, minute)
    }

    public func refresh() async {
        await errors.attempt {
            let document = try await client.serverConfig(server)
            let configured = Set(document.secretsSet)
            var built: [SettingItem] = []
            for key in Self.keys {
                if Self.secretKeys.contains(key) {
                    built.append(SettingItem(key: key, isSecret: true, isSet: configured.contains(key), original: ""))
                } else {
                    let value = document.config[key]
                    built.append(SettingItem(key: key, isSecret: false, isSet: value != nil, original: value?.text ?? ""))
                }
            }
            items = built
            func number(_ key: String) -> Int { document.config[key]?.integer ?? 0 }
            openTime = Self.clock(number("heure_ouverture"), number("minute_ouverture"))
            closeTime = Self.clock(number("heure_fermeture"), number("minute_fermeture"))
            mode = try await client.server(server).mode ?? ""
            applySleep(try await client.sleepSettings(server))
            let java = try await client.serverJava(server)
            let majors = java.runtimes.keys.sorted { (Int($0) ?? Int.max) < (Int($1) ?? Int.max) }
            javaChoices = [Self.systemJava] + majors
            loadedJava = java.servers.first { $0.server == server }?.java?.text ?? Self.systemJava
            javaChoice = loadedJava
        }
    }

    private func applySleep(_ sleep: SleepSettings) {
        loadedSleep = sleep
        sleepEnabled = sleep.enabled
        sleepMinutes = String(sleep.afterS / 60)
        sleepJoinMode = Self.joinModes.contains(sleep.joinMode ?? "") ? sleep.joinMode ?? "kick" : "kick"
        sleepFreeze = sleep.freeze ?? false
    }

    public func saveSleep() async {
        let text = sleepMinutes.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty, text.allSatisfy(\.isNumber), let minutes = Int(text) else {
            errors.show("invalid_value")
            return
        }
        guard minutes >= Self.sleepMinimumMinutes else {
            errors.show("sleep_after_too_short")
            return
        }
        let request = SleepSettingsRequest(
            enabled: sleepEnabled, afterS: minutes * 60,
            joinMode: sleepJoinMode != (loadedSleep.joinMode ?? "kick") ? sleepJoinMode : nil,
            freeze: sleepFreeze != (loadedSleep.freeze ?? false) ? sleepFreeze : nil)
        var saved: SleepSettings?
        if await tab.write({ saved = try await self.client.setSleepSettings(self.server, request: request) }),
           let saved {
            applySleep(saved)
            if !(saved.notes ?? []).isEmpty { tab.restartRequired = true }
            tab.markDone("sleep")
        }
    }

    public func save() async {
        let changed = items.filter(\.isChanged)
        guard !changed.isEmpty else { return }
        let done = await tab.write {
            for item in changed {
                let result = try await self.client.setConfigValue(
                    self.server, key: item.key,
                    value: item.isSecret ? item.value : item.value.trimmingCharacters(in: .whitespacesAndNewlines))
                if result.restartRequired == true { self.tab.restartRequired = true }
            }
        }
        if done { tab.markDone("save") }
        await refresh()
    }

    public func setMode(_ newMode: String) async {
        guard Self.modes.contains(newMode), newMode != mode else { return }
        if await tab.write({ _ = try await self.client.setMode(self.server, mode: newMode) }) {
            mode = newMode
            tab.markDone("mode")
        } else {
            await refresh()
        }
    }

    public func saveSchedule() async {
        guard let open = Self.parseClock(openTime), let close = Self.parseClock(closeTime) else {
            errors.show("invalid_time")
            return
        }
        let schedule = ScheduleRequest(openHour: open.hour, openMinute: open.minute,
                                       closeHour: close.hour, closeMinute: close.minute)
        if await tab.write({ _ = try await self.client.setSchedule(self.server, schedule: schedule) }) {
            tab.markDone("schedule")
        }
    }

    public func saveJava() async {
        guard !javaChoice.isEmpty, javaChoice != loadedJava else { return }
        let choice = javaChoice
        let done = await tab.write {
            let used = try await self.client.setServerJava(self.server, choice: choice)
            if used.restartRequired == true { self.tab.restartRequired = true }
        }
        if done {
            loadedJava = choice
            tab.markDone("java")
        }
    }
}
