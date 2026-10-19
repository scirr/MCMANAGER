import Darwin
import Dispatch
import Foundation

public final class UnixSocketTransport: Transport, @unchecked Sendable {
    private let path: String
    private let timeout: Int
    private let queue = DispatchQueue(label: "mcmanager.socket", qos: .userInitiated, attributes: .concurrent)

    public init(path: String, timeout: Int = 20) {
        self.path = path
        self.timeout = timeout
    }

    public func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    let fd = try self.open(receiveTimeout: self.timeout)
                    defer { Darwin.close(fd) }
                    try Self.writeAll(fd, Self.encode(request))
                    var reader = HTTPReader(fd: fd)
                    let head = try reader.readHead()
                    var body = Data()
                    while let chunk = try reader.readBody() { body.append(chunk) }
                    continuation.resume(returning: HTTPResponse(status: head.status, body: body))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    public func stream(_ request: HTTPRequest) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { continuation in
            let handle = SocketHandle()
            queue.async {
                do {
                    let fd = try self.open(receiveTimeout: 0)
                    handle.set(fd)
                    defer { handle.close() }
                    try Self.writeAll(fd, Self.encode(request))
                    var reader = HTTPReader(fd: fd)
                    let head = try reader.readHead()
                    if !(200..<300).contains(head.status) {
                        var body = Data()
                        while let chunk = try reader.readBody() { body.append(chunk) }
                        throw ApiError.parse(body: body, status: head.status)
                    }
                    while let chunk = try reader.readBody() { continuation.yield(chunk) }
                    continuation.finish()
                } catch {
                    if handle.isClosed {
                        continuation.finish()
                    } else {
                        continuation.finish(throwing: error)
                    }
                }
            }
            continuation.onTermination = { _ in handle.shutdown() }
        }
    }

    private func open(receiveTimeout: Int) throws -> Int32 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw ApiError.unreachable }
        var one: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout<Int32>.size))
        if receiveTimeout > 0 {
            var value = timeval(tv_sec: receiveTimeout, tv_usec: 0)
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &value, socklen_t(MemoryLayout<timeval>.size))
        }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8CString)
        let capacity = MemoryLayout.size(ofValue: address.sun_path)
        guard bytes.count <= capacity else {
            Darwin.close(fd)
            throw ApiError.unreachable
        }
        withUnsafeMutableBytes(of: &address.sun_path) { raw in
            for (index, byte) in bytes.enumerated() { raw[index] = UInt8(bitPattern: byte) }
        }
        let length = socklen_t(MemoryLayout<sockaddr_un>.size)
        let status = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(fd, $0, length) }
        }
        guard status == 0 else {
            Darwin.close(fd)
            throw ApiError.unreachable
        }
        return fd
    }

    static func encode(_ request: HTTPRequest) -> Data {
        var head = "\(request.method) \(request.path) HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
        for (key, value) in request.headers { head += "\(key): \(value)\r\n" }
        if let body = request.body { head += "Content-Length: \(body.count)\r\n" }
        head += "\r\n"
        var data = Data(head.utf8)
        if let body = request.body { data.append(body) }
        return data
    }

    static func writeAll(_ fd: Int32, _ data: Data) throws {
        var offset = 0
        try data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            while offset < raw.count {
                let written = Darwin.write(fd, raw.baseAddress! + offset, raw.count - offset)
                if written < 0 {
                    if errno == EINTR { continue }
                    throw ApiError.unreachable
                }
                offset += written
            }
        }
    }
}

final class SocketHandle: @unchecked Sendable {
    private let lock = NSLock()
    private var fd: Int32 = -1
    private(set) var isClosed = false

    func set(_ value: Int32) {
        lock.lock()
        defer { lock.unlock() }
        fd = value
        if isClosed { Darwin.shutdown(value, SHUT_RDWR) }
    }

    func shutdown() {
        lock.lock()
        defer { lock.unlock() }
        isClosed = true
        if fd >= 0 { Darwin.shutdown(fd, SHUT_RDWR) }
    }

    func close() {
        lock.lock()
        defer { lock.unlock() }
        if fd >= 0 {
            Darwin.close(fd)
            fd = -1
        }
    }
}

struct HTTPReader {
    struct Head {
        var status: Int
        var headers: [String: String]
    }

    private let fd: Int32
    private var pending = Data()
    private var chunked = false
    private var remaining: Int?
    private var chunkLeft = 0
    private var finished = false

    init(fd: Int32) {
        self.fd = fd
    }

    private mutating func fill() throws -> Bool {
        var buffer = [UInt8](repeating: 0, count: 8192)
        while true {
            let count = Darwin.read(fd, &buffer, buffer.count)
            if count > 0 {
                pending.append(contentsOf: buffer[0..<count])
                return true
            }
            if count == 0 { return false }
            if errno == EINTR { continue }
            if errno == EAGAIN || errno == EWOULDBLOCK { throw ApiError.timeout }
            throw ApiError.unreachable
        }
    }

    mutating func readHead() throws -> Head {
        let marker = Data("\r\n\r\n".utf8)
        while pending.range(of: marker) == nil {
            guard try fill() else { throw ApiError.unreachable }
        }
        let range = pending.range(of: marker)!
        let text = String(decoding: pending[pending.startIndex..<range.lowerBound], as: UTF8.self)
        pending = Data(pending[range.upperBound...])
        var lines = text.components(separatedBy: "\r\n")
        let statusLine = lines.removeFirst().split(separator: " ")
        guard statusLine.count >= 2, let status = Int(statusLine[1]) else { throw ApiError.badAnswer(0) }
        var headers: [String: String] = [:]
        for line in lines {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = line[line.startIndex..<colon].lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            headers[key] = value
        }
        chunked = headers["transfer-encoding"]?.lowercased().contains("chunked") ?? false
        remaining = headers["content-length"].flatMap { Int($0) }
        return Head(status: status, headers: headers)
    }

    mutating func readBody() throws -> Data? {
        if finished { return nil }
        if chunked { return try readChunk() }
        if let left = remaining {
            if left == 0 {
                finished = true
                return nil
            }
            if pending.isEmpty, try !fill() {
                finished = true
                return nil
            }
            let take = min(left, pending.count)
            let out = Data(pending.prefix(take))
            pending = Data(pending.dropFirst(take))
            remaining = left - take
            return out
        }
        if pending.isEmpty, try !fill() {
            finished = true
            return nil
        }
        let out = pending
        pending = Data()
        return out
    }

    private mutating func readChunk() throws -> Data? {
        if chunkLeft == 0 {
            let crlf = Data("\r\n".utf8)
            while pending.range(of: crlf) == nil {
                guard try fill() else {
                    finished = true
                    return nil
                }
            }
            var range = pending.range(of: crlf)!
            if range.lowerBound == pending.startIndex {
                pending = Data(pending[range.upperBound...])
                while pending.range(of: crlf) == nil {
                    guard try fill() else {
                        finished = true
                        return nil
                    }
                }
                range = pending.range(of: crlf)!
            }
            let sizeText = String(decoding: pending[pending.startIndex..<range.lowerBound], as: UTF8.self)
            pending = Data(pending[range.upperBound...])
            let hex = sizeText.split(separator: ";").first.map(String.init) ?? "0"
            chunkLeft = Int(hex.trimmingCharacters(in: .whitespaces), radix: 16) ?? 0
            if chunkLeft == 0 {
                finished = true
                return nil
            }
        }
        if pending.isEmpty, try !fill() {
            finished = true
            return nil
        }
        let take = min(chunkLeft, pending.count)
        let out = Data(pending.prefix(take))
        pending = Data(pending.dropFirst(take))
        chunkLeft -= take
        return out
    }
}
