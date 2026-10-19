import Foundation
import Observation

@MainActor
@Observable
public final class TabRunner {
    public private(set) var isBusy = false
    public private(set) var progress = 0.0
    public private(set) var lastDone = ""
    public private(set) var isReadOnly = false
    public var restartRequired = false

    @ObservationIgnored public let client: McClientProtocol
    @ObservationIgnored public let errors: ErrorReporter
    @ObservationIgnored public let server: String
    @ObservationIgnored public var jobPollInterval: Duration = .seconds(1)
    @ObservationIgnored public var jobPollLimit = 3600

    public init(client: McClientProtocol, errors: ErrorReporter, server: String) {
        self.client = client
        self.errors = errors
        self.server = server
    }

    public var canAct: Bool { !isBusy && !isReadOnly }

    public func setBusy(_ value: Bool) { isBusy = value }

    public func markDone(_ kind: String) { lastDone = kind }

    @discardableResult
    public func write(_ work: () async throws -> Void) async -> Bool {
        await errors.attempt {
            do {
                try await work()
            } catch let error as ApiError where error.status == 403 {
                isReadOnly = true
                throw error
            }
        }
    }

    @discardableResult
    public func runJob(_ kind: String, _ start: () async throws -> Job) async -> Bool {
        if isBusy { return false }
        isBusy = true
        progress = 0
        lastDone = ""
        defer { isBusy = false }
        let done = await write {
            var job = try await start()
            var polls = 0
            while polls < jobPollLimit && !job.isFinished {
                try await Task.sleep(for: jobPollInterval)
                job = try await client.job(job.id)
                progress = min(max(Double(job.progress ?? 0), 0), 100)
                polls += 1
            }
            if !job.isFinished { throw ApiError.timeout }
            if job.state != "succeeded" || job.result?.ok == false {
                throw ApiError(code: job.result?.code ?? job.code ?? "job_" + job.state,
                               message: job.result?.message ?? "", status: 200)
            }
        }
        if done { lastDone = kind }
        return done
    }

    public static func formatSize(_ bytes: Int?) -> String {
        guard let bytes else { return "-" }
        var size = Double(bytes)
        let units = ["B", "KB", "MB", "GB"]
        var unit = 0
        while size >= 1024 && unit < units.count - 1 {
            size /= 1024
            unit += 1
        }
        return unit == 0 ? "\(Int(size)) B" : String(format: "%.1f %@", size, units[unit])
    }

    public static func stamp(_ value: String?) -> String {
        (value ?? "").replacingOccurrences(of: "T", with: " ")
    }
}
