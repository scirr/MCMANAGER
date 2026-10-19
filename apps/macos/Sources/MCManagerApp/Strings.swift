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
    default: return error.message.isEmpty ? error.code : error.message
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
