import Foundation

public struct RemoteProfile: Codable, Equatable, Identifiable, Sendable {
    public var name: String
    public var host: String
    public var port: Int
    public var fingerprint: String
    public var deviceId: String
    public var token: String = ""

    public init(name: String, host: String, port: Int, fingerprint: String, deviceId: String = "", token: String = "") {
        self.name = name
        self.host = host
        self.port = port
        self.fingerprint = fingerprint
        self.deviceId = deviceId
        self.token = token
    }

    enum CodingKeys: String, CodingKey {
        case name, host, port, fingerprint, deviceId
    }

    public var id: String { name }
}

public enum HostPort {
    public static func parse(_ text: String) -> (host: String, port: Int)? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let cut = value.lastIndex(of: ":") else { return nil }
        let hostPart = String(value[value.startIndex..<cut])
        let portPart = String(value[value.index(after: cut)...])
        guard !hostPart.isEmpty, let port = Int(portPart), port > 0, port <= 65535 else { return nil }
        let host = hostPart.trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        guard !host.isEmpty, host.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else { return nil }
        return (host, port)
    }
}
