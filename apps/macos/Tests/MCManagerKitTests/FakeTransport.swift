import Foundation
@testable import MCManagerKit

final class FakeTransport: Transport, @unchecked Sendable {
    private let lock = NSLock()
    private var routes: [String: [HTTPResponse]] = [:]
    private var streams: [String: [Data]] = [:]
    private(set) var requests: [HTTPRequest] = []

    func on(_ method: String, _ path: String, status: Int = 200, json: String) {
        lock.lock()
        defer { lock.unlock() }
        routes[method + " " + path, default: []].append(HTTPResponse(status: status, body: Data(json.utf8)))
    }

    func onStream(_ path: String, chunks: [String]) {
        lock.lock()
        defer { lock.unlock() }
        streams[path] = chunks.map { Data($0.utf8) }
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        lock.lock()
        defer { lock.unlock() }
        requests.append(request)
        let key = request.method + " " + request.path
        guard var queue = routes[key], !queue.isEmpty else { throw ApiError.unreachable }
        let response = queue.count > 1 ? queue.removeFirst() : queue[0]
        routes[key] = queue
        return response
    }

    func stream(_ request: HTTPRequest) -> AsyncThrowingStream<Data, Error> {
        lock.lock()
        let chunks = streams[request.path]
        lock.unlock()
        return AsyncThrowingStream { continuation in
            guard let chunks else {
                continuation.finish(throwing: ApiError(code: "not_found", message: "No stream.", status: 404))
                return
            }
            for chunk in chunks { continuation.yield(chunk) }
            continuation.finish()
        }
    }

    func lastBody() -> String {
        lock.lock()
        defer { lock.unlock() }
        return String(decoding: requests.last?.body ?? Data(), as: UTF8.self)
    }
}

enum Samples {
    static let serverList = """
    {"active":"survie","code":"status","ok":true,"schema":1,"servers":[{"active":true,"error":null,"frozen":false,\
    "id":1,"loader":"Fabric","maintenance":false,"mode":"always-on","name":"survie","pid":4821,"port":25565,\
    "rss_kb":6291456,"server":"survie","state":"running","stop_reason":null,"uptime_s":7312,"version":"1.21.1"}]}
    """

    static let serverStopped = """
    {"active":true,"code":"status","ok":true,"name":"survie","server":"survie","state":"stopped","loader":"Fabric",\
    "version":"1.21.1","rss_kb":null,"error":null}
    """

    static let serverRunning = """
    {"active":true,"code":"status","ok":true,"name":"survie","server":"survie","state":"running","loader":"Fabric",\
    "version":"1.21.1","rss_kb":2097152,"error":null}
    """

    static let players = """
    {"code":"players","max":20,"ok":true,"online":2,"players":["Steve","Alex"],"schema":1,"server":"survie","state":"running"}
    """

    static let offline = """
    {"code":"server_offline","max":null,"message":"The server is offline: no players.","ok":false,"online":0,\
    "players":[],"schema":1,"server":"survie","state":"stopped"}
    """

    static let notFound = """
    {"code":"not_found","message":"No server matches 'survie'.","ok":false}
    """
}
