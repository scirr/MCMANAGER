import Foundation
import Observation

@MainActor
@Observable
public final class ServerDetailViewModel {
    private static let startable: Set<String> = ["stopped", "crashed", "stopped-by-user", "closed"]
    private static let stoppable: Set<String> = ["running", "starting", "sleeping"]

    public let name: String
    public let console: ConsoleViewModel
    public let players: PlayersViewModel
    public let backups: BackupsViewModel
    public let mods: ModsViewModel
    public let datapacks: DatapacksViewModel
    public let world: WorldViewModel
    public let tasks: TasksViewModel
    public let settings: SettingsViewModel
    public private(set) var state = ""
    public private(set) var version = ""
    public private(set) var ramText = "-"
    public private(set) var isBusy = false

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter
    @ObservationIgnored public var jobPollInterval: Duration = .seconds(1)
    @ObservationIgnored public var jobPollLimit = 120

    public init(client: McClientProtocol, errors: ErrorReporter, name: String) {
        self.client = client
        self.errors = errors
        self.name = name
        console = ConsoleViewModel(client: client, errors: errors, server: name)
        players = PlayersViewModel(client: client, errors: errors, server: name)
        backups = BackupsViewModel(client: client, errors: errors, server: name)
        mods = ModsViewModel(client: client, errors: errors, server: name)
        datapacks = DatapacksViewModel(client: client, errors: errors, server: name)
        world = WorldViewModel(client: client, errors: errors, server: name)
        tasks = TasksViewModel(client: client, errors: errors, server: name)
        settings = SettingsViewModel(client: client, errors: errors, server: name)
    }

    public var canStart: Bool { !isBusy && Self.startable.contains(state) }
    public var canStop: Bool { !isBusy && Self.stoppable.contains(state) }
    public var canRestart: Bool { !isBusy && state == "running" }
    public var canResume: Bool { !isBusy && state == "maintenance" }

    public func refresh() async {
        await errors.attempt {
            let snapshot = try await client.server(name)
            state = snapshot.error != nil ? "error" : snapshot.state ?? ""
            version = [snapshot.loader, snapshot.version].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " ")
            ramText = ServerListViewModel.formatRam(snapshot.rssKb)
        }
        await players.loadOnline()
    }

    public func start() async { await act { _ = try await self.client.start(self.name) } }

    public func stop() async { await act { _ = try await self.client.stop(self.name, request: nil) } }

    public func resume() async { await act { _ = try await self.client.resume(self.name) } }

    public func restart() async {
        await act {
            var job = try await self.client.restart(self.name)
            var polls = 0
            while polls < self.jobPollLimit && !job.isFinished {
                try await Task.sleep(for: self.jobPollInterval)
                job = try await self.client.job(job.id)
                polls += 1
            }
            if job.state == "failed" || job.state == "cancelled" {
                throw ApiError(code: job.result?.code ?? job.code ?? "job_" + job.state,
                               message: job.result?.message ?? "", status: 200)
            }
        }
    }

    private func act(_ work: () async throws -> Void) async {
        isBusy = true
        await errors.attempt(work)
        isBusy = false
        await refresh()
    }
}
