import Foundation
import Observation

@MainActor
@Observable
public final class ErrorReporter {
    public var current: ApiError?

    public init() {}

    public func report(_ error: Error) {
        if error is CancellationError { return }
        current = (error as? ApiError) ?? ApiError(code: "unknown", message: error.localizedDescription)
    }

    public func dismiss() { current = nil }

    @discardableResult
    public func attempt(_ work: () async throws -> Void) async -> Bool {
        do {
            try await work()
            return true
        } catch {
            report(error)
            return false
        }
    }
}
