import Foundation
import Observation

public struct TaskItem: Equatable, Identifiable, Sendable {
    public let id: Int
    public let name: String
    public let kind: String
    public let cron: String
    public let command: String
    public let enabled: Bool
    public let nextRun: String
    public let lastRun: String
    public let lastResult: String
    public let warnText: String
}

@MainActor
@Observable
public final class TasksViewModel {
    public static let actions = ["restart", "backup", "command", "stop", "start"]

    public private(set) var items: [TaskItem] = []
    public var newName = ""
    public var newCron = ""
    public var newAction = "restart"
    public var newCommand = ""
    public var newWarn = ""
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter
    @ObservationIgnored private let server: String

    public init(client: McClientProtocol, errors: ErrorReporter, server: String) {
        self.client = client
        self.errors = errors
        self.server = server
        tab = TabRunner(client: client, errors: errors, server: server)
    }

    public var isEmpty: Bool { items.isEmpty }
    public var needsCommand: Bool { newAction == "command" }
    public var allowsWarn: Bool { newAction == "restart" || newAction == "stop" }

    public static func formatWarn(_ seconds: Int) -> String {
        seconds % 60 == 0 ? "\(seconds / 60)m" : "\(seconds)s"
    }

    public func refresh() async {
        await errors.attempt {
            let tasks = try await client.listTasks(server)
            items = tasks.map { task in
                let result: String
                if let last = task.lastResult {
                    result = last.ok == true ? "ok" : (last.code ?? "error")
                } else {
                    result = ""
                }
                return TaskItem(id: task.id, name: task.name ?? "", kind: task.action ?? "", cron: task.cron ?? "",
                                command: task.command ?? "", enabled: task.enabled ?? false,
                                nextRun: TabRunner.stamp(task.nextRun), lastRun: TabRunner.stamp(task.lastRun),
                                lastResult: result, warnText: (task.warn ?? []).map(Self.formatWarn).joined(separator: ", "))
            }
        }
    }

    public func create() async {
        let cron = newCron.trimmingCharacters(in: .whitespacesAndNewlines)
        let command = newCommand.trimmingCharacters(in: .whitespacesAndNewlines)
        if cron.isEmpty {
            errors.show("cron_required")
            return
        }
        if needsCommand && command.isEmpty {
            errors.show("command_required")
            return
        }
        let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        let warn = newWarn.trimmingCharacters(in: .whitespacesAndNewlines)
        let request = TaskCreateRequest(cron: cron, action: newAction, name: name.isEmpty ? nil : name,
                                        command: needsCommand ? command : nil,
                                        warn: allowsWarn && !warn.isEmpty ? warn : nil)
        let done = await tab.write { _ = try await self.client.createTask(self.server, request: request) }
        if done {
            newName = ""
            newCron = ""
            newCommand = ""
            newWarn = ""
            await refresh()
        }
    }

    public func setEnabled(_ id: Int, enabled: Bool) async {
        if await tab.write({ _ = try await self.client.updateTask(self.server, task: id, enabled: enabled) }) {
            await refresh()
        }
    }

    public func delete(_ id: Int, confirmed: Bool) async {
        guard confirmed else { return }
        if await tab.write({ _ = try await self.client.deleteTask(self.server, task: id) }) {
            await refresh()
        }
    }

    public func run(_ id: Int) async {
        await tab.runJob("run") { try await self.client.runTask(self.server, task: id, skipWarn: false) }
        await refresh()
    }
}
