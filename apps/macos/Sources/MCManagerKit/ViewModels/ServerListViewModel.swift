import Foundation
import Observation

@MainActor
@Observable
public final class ServerListViewModel {
    public private(set) var servers: [ServerSnapshot] = []
    public var selection: String?
    public private(set) var isLoading = false

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored public let errors: ErrorReporter
    @ObservationIgnored private var pollTask: Task<Void, Never>?

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        self.errors = errors
    }

    public func refresh() async {
        isLoading = true
        defer { isLoading = false }
        await errors.attempt {
            let list = try await client.listServers()
            servers = list
            if let selected = selection, !list.contains(where: { $0.name == selected }) {
                selection = nil
            }
            if selection == nil {
                selection = list.first(where: { $0.active == true })?.name ?? list.first?.name
            }
        }
    }

    public func startPolling(every interval: Duration = .seconds(5)) {
        stopPolling()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refreshQuietly()
                try? await Task.sleep(for: interval)
            }
        }
    }

    public func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func refreshQuietly() async {
        if let list = try? await client.listServers() {
            servers = list
        }
    }

    public static func formatRam(_ kilobytes: Int?) -> String {
        guard let kilobytes, kilobytes > 0 else { return "-" }
        let gigabytes = Double(kilobytes) / 1_048_576
        if gigabytes >= 1 { return String(format: "%.1f GB", gigabytes) }
        return String(format: "%.0f MB", Double(kilobytes) / 1024)
    }
}
