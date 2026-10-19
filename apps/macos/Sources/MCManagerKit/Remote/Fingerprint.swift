import CryptoKit
import Foundation

public enum Fingerprint {
    public static func format(_ der: Data) -> String {
        SHA256.hash(data: der).map { String(format: "%02X", $0) }.joined(separator: ":")
    }

    public static func isValid(_ value: String?) -> Bool {
        guard let value, value.utf8.count == 95 else { return false }
        for (index, byte) in value.utf8.enumerated() {
            if index % 3 == 2 {
                if byte != UInt8(ascii: ":") { return false }
            } else {
                let digit = (byte >= 48 && byte <= 57) || (byte >= 65 && byte <= 70) || (byte >= 97 && byte <= 102)
                if !digit { return false }
            }
        }
        return true
    }

    public static func equal(_ left: String?, _ right: String?) -> Bool {
        guard let left, let right else { return false }
        let a = Array(left.uppercased().utf8)
        let b = Array(right.uppercased().utf8)
        var difference = a.count ^ b.count
        for index in 0..<min(a.count, b.count) {
            difference |= Int(a[index] ^ b[index])
        }
        return difference == 0
    }

    public static func accepts(pinned: String?, presentedDER: Data?) -> Bool {
        guard let presentedDER, isValid(pinned) else { return false }
        return equal(pinned, format(presentedDER))
    }
}
