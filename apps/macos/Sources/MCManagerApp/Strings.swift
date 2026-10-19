import Foundation
import MCManagerKit

func tr(_ key: String.LocalizationValue) -> String {
    String(localized: key, bundle: .module)
}

func stateLabel(_ state: String) -> String {
    switch state {
    case "running": return tr("Running")
    case "starting": return tr("Starting")
    case "stopped", "stopped-by-user", "closed": return tr("Stopped")
    case "crashed": return tr("Crashed")
    case "sleeping": return tr("Sleeping")
    case "maintenance": return tr("Maintenance")
    case "error": return tr("Error")
    case "": return "-"
    default: return state
    }
}

func message(for error: ApiError) -> String {
    switch error.code {
    case "daemon_unreachable": return tr("The MC Manager service is not reachable. Check that it is running.")
    case "daemon_timeout": return tr("The MC Manager service did not answer in time.")
    case "bad_answer": return tr("The MC Manager service sent an answer the app cannot read.")
    case "server_offline": return tr("The server is offline.")
    case "port_taken": return tr("The server port is already in use.")
    default:
        if let text = errorTexts[error.code] { return String(localized: text, bundle: .module) }
        return error.message.isEmpty ? error.code : error.message
    }
}

func kindLabel(_ kind: String) -> String {
    switch kind {
    case "whitelist": return tr("Whitelist")
    case "op": return tr("Operators")
    case "ban": return tr("Banned players")
    case "banip": return tr("Banned addresses")
    default: return kind
    }
}

func originLabel(_ type: String) -> String {
    switch type {
    case "midi": return tr("Noon (automatic)")
    case "minuit": return tr("Midnight (automatic)")
    case "manual": return tr("Manual")
    case "pre-restore", "pre_restore": return tr("Before a restore")
    case "upgrade": return tr("Before an update")
    default: return type
    }
}

func dimensionLabel(_ id: String) -> String {
    switch id {
    case "overworld": return tr("Overworld")
    case "nether", "the_nether": return tr("Nether")
    case "end", "the_end": return tr("End")
    default: return id
    }
}

func taskActionLabel(_ action: String) -> String {
    switch action {
    case "restart": return tr("Restart")
    case "backup": return tr("Backup")
    case "command": return tr("Command")
    case "stop": return tr("Stop")
    case "start": return tr("Start")
    default: return action
    }
}

func datapackProblemLabel(_ problem: String) -> String {
    switch problem {
    case "nested": return tr("nested folder: not usable")
    case "not_a_pack": return tr("not a datapack")
    default: return problem
    }
}

func modeLabel(_ mode: String) -> String {
    switch mode {
    case "schedule": return tr("Schedule")
    case "always-on": return tr("Always on")
    case "maintenance": return tr("Maintenance")
    default: return mode
    }
}

func javaChoiceLabel(_ choice: String) -> String {
    choice == SettingsViewModel.systemJava ? tr("System Java") : "Java " + choice
}

func sourceLabel(_ source: String) -> String {
    switch source {
    case "auto": return tr("Automatic")
    case "modrinth": return "Modrinth"
    case "curseforge": return "CurseForge"
    case "hangar": return "Hangar"
    default: return source
    }
}

func settingLabel(_ key: String) -> String {
    switch key {
    case "nom_serveur": return tr("Server name")
    case "port": return tr("Port")
    case "rcon_port": return tr("RCON port")
    case "ram_allocation": return tr("Memory (e.g. 4G)")
    case "cpu_affinity": return tr("CPU affinity")
    case "jar_name": return tr("Server jar")
    case "domaine": return tr("Domain")
    case "dossier_backup": return tr("Backup folder")
    case "backup_retention_days": return tr("Backup retention (days)")
    case "backup_keep": return tr("Backups kept")
    case "stop_timeout": return tr("Stop timeout (s)")
    case "internal_port": return tr("Internal port")
    case "metrics_bind": return tr("Metrics address")
    case "metrics_allow_remote": return tr("Metrics from remote (0/1)")
    case "sleep_freeze": return tr("Sleep: freeze (0/1)")
    case "sleep_hold_timeout": return tr("Sleep: hold timeout (s)")
    case "sleep_join_mode": return tr("Sleep: join mode (kick/hold)")
    case "sleep_proxy_protocol": return tr("Sleep: proxy protocol (auto/on/off)")
    case "mcrcon_pass": return tr("RCON password")
    case "webhook_url": return tr("Webhook URL")
    case "curseforge_api_key": return tr("CurseForge API key")
    case "backup_encrypt_key_file": return tr("Backup encryption key file")
    default: return key
    }
}

func lastResultLabel(_ result: String) -> String {
    if result.isEmpty { return "" }
    if result == "ok" { return tr("last run: ok") }
    let reason = errorTexts[result].map { String(localized: $0, bundle: .module) } ?? result
    return String(format: tr("last run failed: %@"), reason)
}
