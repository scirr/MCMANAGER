import Foundation
import Observation

@MainActor
@Observable
public final class ConsoleViewModel {
    public static let maxLines = 1000

    public private(set) var lines: [String] = []
    public var commandText = ""
    public private(set) var isStreaming = false

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter
    @ObservationIgnored private let server: String
    @ObservationIgnored private var task: Task<Void, Never>?

    public init(client: McClientProtocol, errors: ErrorReporter, server: String) {
        self.client = client
        self.errors = errors
        self.server = server
    }

    public var completion: Task<Void, Never>? { task }

    public func start() {
        stop()
        task = Task { [weak self] in await self?.run() }
    }

    public func stop() {
        task?.cancel()
        task = nil
    }

    private func run() async {
        isStreaming = true
        defer { isStreaming = false }
        do {
            for try await event in client.streamConsole(server, tail: 200) where event.name == "line" || event.name == "message" {
                append(event.data)
            }
        } catch {
            errors.report(error)
        }
    }

    public func send() async {
        let command = commandText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !command.isEmpty else { return }
        commandText = ""
        await errors.attempt {
            append("> " + command)
            let reply = try await client.sendCommand(server, command: command)
            if let output = reply.output, !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                for line in output.split(separator: "\n", omittingEmptySubsequences: false) {
                    append(String(line).trimmingCharacters(in: CharacterSet(charactersIn: "\r")))
                }
            }
        }
    }

    private func append(_ line: String) {
        lines.append(line)
        if lines.count > Self.maxLines {
            lines.removeFirst(lines.count - Self.maxLines)
        }
    }
}
