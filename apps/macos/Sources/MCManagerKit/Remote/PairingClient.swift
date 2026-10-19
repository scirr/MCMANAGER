import Foundation

public protocol PairingProtocol: Sendable {
    func fetchFingerprint(host: String, port: Int) async throws -> String
    func pair(host: String, port: Int, fingerprint: String, code: String, name: String) async throws -> RemoteProfile
}

struct PairRequest: Codable { var code: String; var name: String }

struct PairResult: Codable {
    var ok: Bool?
    var deviceId: String?
    var token: String?
    var fingerprint: String?
}

public struct PairingClient: PairingProtocol {
    private let makeTransport: @Sendable (String, Int, String) -> Transport

    public init(makeTransport: (@Sendable (String, Int, String) -> Transport)? = nil) {
        self.makeTransport = makeTransport ?? { host, port, fingerprint in
            PairingTransport(host: host, port: port, fingerprint: fingerprint)
        }
    }

    public func fetchFingerprint(host: String, port: Int) async throws -> String {
        let delegate = PinnedSessionDelegate(pinned: nil)
        let session = pinnedSession(delegate: delegate, timeout: 20)
        defer { session.invalidateAndCancel() }
        guard let url = RemoteTransport.baseURL(host: host, port: port) else {
            throw ApiError(code: "bad_address")
        }
        do {
            _ = try await session.data(from: url)
        } catch {
            if let seen = delegate.presented { return seen }
            if error is CancellationError { throw error }
            throw ApiError(code: "remote_unreachable")
        }
        if let seen = delegate.presented { return seen }
        throw ApiError(code: "remote_unreachable")
    }

    public func pair(host: String, port: Int, fingerprint: String, code: String, name: String) async throws -> RemoteProfile {
        guard Fingerprint.isValid(fingerprint) else { throw ApiError(code: "fingerprint_missing") }
        let transport = makeTransport(host, port, fingerprint)
        var request = HTTPRequest(method: "POST", path: "/v1/pair")
        request.body = try Coding.encoder.encode(PairRequest(code: code, name: name))
        request.headers["Content-Type"] = "application/json"
        let response: HTTPResponse
        do {
            response = try await transport.send(request)
        } catch let error as ApiError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw ApiError(code: "remote_unreachable")
        }
        guard response.status == 201 else {
            throw ApiError.parse(body: response.body, status: response.status)
        }
        guard let result = try? Coding.decoder.decode(PairResult.self, from: response.body),
              result.ok != false, let token = result.token, !token.isEmpty else {
            throw ApiError.badAnswer(response.status)
        }
        if let reported = result.fingerprint, !reported.isEmpty, !Fingerprint.equal(reported, fingerprint) {
            throw ApiError(code: "fingerprint_mismatch", status: response.status)
        }
        return RemoteProfile(name: name, host: host, port: port, fingerprint: fingerprint.uppercased(),
                             deviceId: result.deviceId ?? "", token: token)
    }
}

struct PairingTransport: Transport {
    let host: String
    let port: Int
    let fingerprint: String

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let inner = try RemoteTransport(host: host, port: port, fingerprint: fingerprint, token: "", allowAnonymous: true)
        return try await inner.send(request)
    }

    func stream(_ request: HTTPRequest) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { $0.finish(throwing: ApiError(code: "remote_unreachable")) }
    }
}
