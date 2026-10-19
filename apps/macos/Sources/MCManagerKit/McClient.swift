import Foundation

public protocol McClientProtocol: Sendable {
    func listServers() async throws -> [ServerSnapshot]
    func server(_ name: String) async throws -> ServerSnapshot
    func start(_ name: String) async throws -> OperationResult
    func stop(_ name: String, request: StopRequest?) async throws -> OperationResult
    func restart(_ name: String) async throws -> Job
    func resume(_ name: String) async throws -> OperationResult
    func sendCommand(_ name: String, command: String) async throws -> OperationResult
    func streamConsole(_ name: String, tail: Int) -> AsyncThrowingStream<ConsoleEvent, Error>
    func onlinePlayers(_ name: String) async throws -> PlayersOnline
    func playerList(_ name: String, kind: String) async throws -> PlayerListing
    func addToList(_ name: String, kind: String, subject: String, reason: String?) async throws -> OperationResult
    func removeFromList(_ name: String, kind: String, subject: String) async throws -> OperationResult
    func kick(_ name: String, player: String, reason: String?) async throws -> OperationResult
    func job(_ id: String) async throws -> Job
}

public struct McClient: McClientProtocol {
    private let transport: Transport

    public init(transport: Transport) {
        self.transport = transport
    }

    public static func local(runFolders: [String]? = nil) -> McClient? {
        guard let path = ApiLocator.socketPath(runFolders: runFolders) else { return nil }
        return McClient(transport: UnixSocketTransport(path: path))
    }

    private static func ref(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    private static func serverPath(_ name: String) -> String { "/v1/servers/" + ref(name) }

    private func call<T: Decodable>(_ method: String, _ path: String, body: (any Encodable)? = nil,
                                    as type: T.Type? = nil) async throws -> T {
        var request = HTTPRequest(method: method, path: path)
        if let body {
            request.body = try Coding.encoder.encode(AnyEncodable(body))
            request.headers["Content-Type"] = "application/json"
        }
        let response: HTTPResponse
        do {
            response = try await transport.send(request)
        } catch let error as ApiError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw ApiError.unreachable
        }
        guard (200..<300).contains(response.status) else {
            throw ApiError.parse(body: response.body, status: response.status)
        }
        if let envelope = try? JSONDecoder().decode(ErrorBody.self, from: response.body), envelope.ok == false {
            throw ApiError.parse(body: response.body, status: response.status)
        }
        do {
            return try Coding.decoder.decode(T.self, from: response.body)
        } catch {
            throw ApiError.badAnswer(response.status)
        }
    }

    public func listServers() async throws -> [ServerSnapshot] {
        try await call("GET", "/v1/servers", as: ServerList.self).servers
    }

    public func server(_ name: String) async throws -> ServerSnapshot {
        try await call("GET", Self.serverPath(name))
    }

    public func start(_ name: String) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/start")
    }

    public func stop(_ name: String, request: StopRequest? = nil) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/stop", body: request)
    }

    public func restart(_ name: String) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/restart")
    }

    public func resume(_ name: String) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/resume")
    }

    public func sendCommand(_ name: String, command: String) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/console", body: ConsoleCommand(command: command))
    }

    public func onlinePlayers(_ name: String) async throws -> PlayersOnline {
        try await call("GET", Self.serverPath(name) + "/players")
    }

    public func playerList(_ name: String, kind: String) async throws -> PlayerListing {
        try await call("GET", Self.serverPath(name) + "/lists/" + Self.ref(kind))
    }

    public func addToList(_ name: String, kind: String, subject: String, reason: String?) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/lists/" + Self.ref(kind),
                       body: PlayerListAdd(subject: subject, reason: reason))
    }

    public func removeFromList(_ name: String, kind: String, subject: String) async throws -> OperationResult {
        try await call("DELETE", Self.serverPath(name) + "/lists/" + Self.ref(kind) + "/" + Self.ref(subject))
    }

    public func kick(_ name: String, player: String, reason: String?) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/kick", body: KickRequest(player: player, reason: reason))
    }

    public func job(_ id: String) async throws -> Job {
        try await call("GET", "/v1/jobs/" + Self.ref(id))
    }

    public func streamConsole(_ name: String, tail: Int = 200) -> AsyncThrowingStream<ConsoleEvent, Error> {
        let request = HTTPRequest(method: "GET", path: Self.serverPath(name) + "/console?tail=\(tail)",
                                  headers: ["Accept": "text/event-stream"])
        let chunks = transport.stream(request)
        return AsyncThrowingStream { continuation in
            let task = Task {
                var parser = SSEParser()
                do {
                    for try await chunk in chunks {
                        for event in parser.feed(chunk) { continuation.yield(event) }
                    }
                    continuation.finish()
                } catch let error as ApiError {
                    continuation.finish(throwing: error)
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: ApiError.unreachable)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

private struct AnyEncodable: Encodable {
    private let encodeValue: (Encoder) throws -> Void

    init(_ value: any Encodable) {
        encodeValue = { try value.encode(to: $0) }
    }

    func encode(to encoder: Encoder) throws { try encodeValue(encoder) }
}
