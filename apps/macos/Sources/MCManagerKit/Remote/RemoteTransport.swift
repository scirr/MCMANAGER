import Foundation

public struct RemoteTransport: Transport {
    private let base: URL
    private let token: String
    private let session: URLSession
    private let delegate: PinnedSessionDelegate

    public init(host: String, port: Int, fingerprint: String, token: String, allowAnonymous: Bool = false,
                timeout: TimeInterval = 20) throws {
        guard Fingerprint.isValid(fingerprint), !token.isEmpty || allowAnonymous,
              let url = Self.baseURL(host: host, port: port) else {
            throw ApiError(code: "fingerprint_missing")
        }
        base = url
        self.token = token
        delegate = PinnedSessionDelegate(pinned: fingerprint)
        session = pinnedSession(delegate: delegate, timeout: timeout)
    }

    public init(profile: RemoteProfile, timeout: TimeInterval = 20) throws {
        try self.init(host: profile.host, port: profile.port, fingerprint: profile.fingerprint,
                      token: profile.token, timeout: timeout)
    }

    static func baseURL(host: String, port: Int) -> URL? {
        var components = URLComponents()
        components.scheme = "https"
        components.host = host
        components.port = port
        return components.url
    }

    func urlRequest(_ request: HTTPRequest) throws -> URLRequest {
        guard let url = URL(string: request.path, relativeTo: base)?.absoluteURL else {
            throw ApiError.unreachable
        }
        var built = URLRequest(url: url)
        built.httpMethod = request.method
        built.httpBody = request.body
        for (name, value) in request.headers { built.setValue(value, forHTTPHeaderField: name) }
        if !token.isEmpty { built.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        return built
    }

    private func failure(_ error: Error) -> Error {
        if error is ApiError || error is CancellationError { return error }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .timedOut: return ApiError.timeout
            case .cancelled, .serverCertificateUntrusted, .secureConnectionFailed, .clientCertificateRejected:
                return ApiError(code: "fingerprint_mismatch")
            default: return ApiError(code: "remote_unreachable")
            }
        }
        return ApiError(code: "remote_unreachable")
    }

    public func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let built = try urlRequest(request)
        do {
            let (data, response) = try await session.data(for: built)
            guard let http = response as? HTTPURLResponse else { throw ApiError.badAnswer(0) }
            return HTTPResponse(status: http.statusCode, body: data)
        } catch {
            throw failure(error)
        }
    }

    public func stream(_ request: HTTPRequest) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let built = try urlRequest(request)
                    let (bytes, response) = try await session.bytes(for: built)
                    guard let http = response as? HTTPURLResponse else { throw ApiError.badAnswer(0) }
                    if !(200..<300).contains(http.statusCode) {
                        var body = Data()
                        for try await byte in bytes { body.append(byte) }
                        throw ApiError.parse(body: body, status: http.statusCode)
                    }
                    var line = Data()
                    for try await byte in bytes {
                        line.append(byte)
                        if byte == 10 {
                            continuation.yield(line)
                            line = Data()
                        }
                    }
                    if !line.isEmpty { continuation.yield(line) }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: failure(error))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
