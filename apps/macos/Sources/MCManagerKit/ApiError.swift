import Foundation

public struct ApiError: Error, Equatable, Sendable, LocalizedError {
    public let code: String
    public let message: String
    public let status: Int

    public init(code: String, message: String = "", status: Int = 0) {
        self.code = code
        self.message = message
        self.status = status
    }

    public var errorDescription: String? { message.isEmpty ? code : message }

    public static let unreachable = ApiError(code: "daemon_unreachable")
    public static let timeout = ApiError(code: "daemon_timeout")

    static func badAnswer(_ status: Int) -> ApiError {
        ApiError(code: "bad_answer", status: status)
    }

    static func parse(body: Data, status: Int) -> ApiError {
        guard let envelope = try? JSONDecoder().decode(ErrorBody.self, from: body) else {
            return badAnswer(status)
        }
        return ApiError(code: envelope.code ?? "unknown", message: envelope.message ?? "", status: status)
    }
}

struct ErrorBody: Decodable {
    var ok: Bool?
    var code: String?
    var message: String?
}
