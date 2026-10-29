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
    case "alert_test_failed":
        return error.message.isEmpty
            ? tr("The test message could not be delivered")
            : String(format: tr("The test failed for: %@"), error.message)
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

func joinModeLabel(_ mode: String) -> String {
    switch mode {
    case "kick": return tr("Refuse while it wakes (kick)")
    case "hold": return tr("Hold until it is up (hold)")
    default: return mode
    }
}

func placementLabel(_ placement: String) -> String {
    switch placement {
    case "default": return tr("Default")
    case "first": return tr("After built-in packs")
    case "last": return tr("Last")
    case "before_vanilla": return tr("Before vanilla")
    default: return placement
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
    case "sleep_hold_timeout": return tr("Sleep: hold timeout (s)")
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

func alertTypeLabel(_ type: String) -> String {
    switch type {
    case "email": return tr("Email")
    case "telegram": return "Telegram"
    case "ntfy": return "ntfy"
    case "webhook": return "Webhook"
    case "discord": return "Discord"
    default: return type
    }
}

func alertEventLabel(_ event: String) -> String {
    switch event {
    case "start": return tr("Start")
    case "stop": return tr("Stop")
    case "crash": return tr("Crash")
    case "crash_loop": return tr("Repeated crashes")
    case "backup_failed": return tr("Backup failed")
    case "update": return tr("Update")
    case "sleep": return tr("Sleep")
    case "wake": return tr("Wake-up")
    default: return event
    }
}

func alertFieldLabel(_ key: String) -> String {
    switch key {
    case "host": return tr("SMTP server")
    case "port": return tr("Port (587 by default)")
    case "user": return tr("User")
    case "password": return tr("Password")
    case "sender": return tr("Sender address")
    case "to": return tr("Recipients (comma-separated)")
    case "token": return tr("Token")
    case "chat_id": return tr("Chat identifier")
    case "server": return tr("ntfy server (optional)")
    case "topic": return tr("Topic")
    case "url": return tr("Address (URL)")
    case "secret": return tr("Signing secret (optional)")
    default: return key
    }
}

func roleLabel(_ role: String) -> String {
    switch role {
    case "viewer": return tr("Viewer")
    case "operator": return tr("Operator")
    case "admin": return tr("Administrator")
    default: return role
    }
}

func notificationPrefLabel(_ kind: String) -> String {
    switch kind {
    case "crash": return tr("A server crashes")
    case "backup_failed": return tr("A backup fails")
    case "join": return tr("A player joins")
    default: return kind
    }
}

func noticeTitle(_ notice: AppNotice) -> String {
    switch notice.kind {
    case "crash": return String(format: tr("%@ crashed"), notice.server)
    case "crash_loop": return String(format: tr("%@ keeps crashing"), notice.server)
    case "backup_failed": return String(format: tr("Backup of %@ failed"), notice.server)
    default: return String(format: tr("Player joined %@"), notice.server)
    }
}

func doneLabel(_ kind: String) -> String? {
    switch kind {
    case "alert_added": return tr("Channel added")
    case "alert_tested": return tr("Test message sent")
    case "alert_removed": return tr("Channel removed")
    case "java_installed": return tr("Java installed")
    case "java_removed": return tr("Java removed")
    case "remote_enabled": return tr("Remote access enabled")
    case "remote_disabled": return tr("Remote access disabled")
    case "code_ready": return tr("Pairing code generated")
    case "role_saved": return tr("Role changed")
    case "device_revoked": return tr("Device revoked")
    case "update_done": return tr("Update installed")
    case "update_rolled_back": return tr("Previous version restored")
    case "router_enabled": return tr("Router enabled")
    case "router_disabled": return tr("Router disabled")
    case "route_saved": return tr("Route saved")
    case "route_removed": return tr("Route removed")
    case "router_default_saved": return tr("Default server saved")
    case "router_access_saved": return tr("Access list changed")
    case "modpack_updated": return tr("Modpack updated")
    case "modpack_current": return tr("The modpack is already up to date")
    default: return nil
    }
}
