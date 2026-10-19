import Foundation

public struct HTTPRequest: Equatable, Sendable {
    public var method: String
    public var path: String
    public var body: Data?
    public var headers: [String: String]

    public init(method: String, path: String, body: Data? = nil, headers: [String: String] = [:]) {
        self.method = method
        self.path = path
        self.body = body
        self.headers = headers
    }
}

public struct HTTPResponse: Equatable, Sendable {
    public var status: Int
    public var body: Data

    public init(status: Int, body: Data) {
        self.status = status
        self.body = body
    }
}

public protocol Transport: Sendable {
    func send(_ request: HTTPRequest) async throws -> HTTPResponse
    func stream(_ request: HTTPRequest) -> AsyncThrowingStream<Data, Error>
}
