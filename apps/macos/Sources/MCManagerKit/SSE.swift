import Foundation

public struct SSEParser {
    private var buffer = Data()
    private var name: String?
    private var id: String?
    private var data: [String] = []

    public init() {}

    public mutating func feed(_ chunk: Data) -> [ConsoleEvent] {
        buffer.append(chunk)
        var events: [ConsoleEvent] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            var lineData = buffer[buffer.startIndex..<newline]
            buffer = Data(buffer[buffer.index(after: newline)...])
            if lineData.last == 0x0D { lineData = lineData.dropLast() }
            let line = String(decoding: lineData, as: UTF8.self)
            if let event = consume(line) { events.append(event) }
        }
        return events
    }

    private mutating func consume(_ line: String) -> ConsoleEvent? {
        if line.isEmpty {
            defer { name = nil; data = [] }
            if name != nil || !data.isEmpty {
                return ConsoleEvent(id: id, name: name ?? "message", data: data.joined(separator: "\n"))
            }
            return nil
        }
        if line.hasPrefix(":") { return nil }
        let key: String
        var value: String
        if let colon = line.firstIndex(of: ":") {
            key = String(line[line.startIndex..<colon])
            value = String(line[line.index(after: colon)...])
            if value.hasPrefix(" ") { value.removeFirst() }
        } else {
            key = line
            value = ""
        }
        switch key {
        case "event": name = value
        case "data": data.append(value)
        case "id": id = value
        default: break
        }
        return nil
    }
}
