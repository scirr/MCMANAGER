import AppKit
import MCManagerKit
import UserNotifications

@MainActor
final class NativeNotifier {
    private var asked = false

    private var available: Bool { Bundle.main.bundleURL.pathExtension == "app" }

    func deliver(_ notice: AppNotice) {
        guard available, !NSApplication.shared.isActive else { return }
        let title = noticeTitle(notice)
        let body = notice.detail
        let identifier = notice.id
        let ask = !asked
        asked = true
        Task {
            let center = UNUserNotificationCenter.current()
            if ask { _ = try? await center.requestAuthorization(options: [.alert, .sound]) }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            try? await center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil))
        }
    }
}
