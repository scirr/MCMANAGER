import XCTest

final class LocalizationTests: XCTestCase {
    private let appFolder = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/MCManagerApp")

    private func catalog() throws -> [String: [String: Any]] {
        let data = try Data(contentsOf: appFolder.appendingPathComponent("Localizable.xcstrings"))
        let root = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        return try XCTUnwrap(root["strings"] as? [String: [String: Any]])
    }

    private func french(_ entry: [String: Any]) -> String? {
        let localizations = entry["localizations"] as? [String: Any]
        let fr = localizations?["fr"] as? [String: Any]
        let unit = fr?["stringUnit"] as? [String: Any]
        guard unit?["state"] as? String == "translated" else { return nil }
        return unit?["value"] as? String
    }

    private func literals(_ pattern: String, in file: String) throws -> [String] {
        let text = try String(contentsOf: appFolder.appendingPathComponent(file), encoding: .utf8)
        let expression = try NSRegularExpression(pattern: pattern, options: [.anchorsMatchLines])
        let range = NSRange(text.startIndex..., in: text)
        return expression.matches(in: text, range: range).compactMap { match in
            Range(match.range(at: 1), in: text).map { String(text[$0]) }
        }
    }

    func testEveryEntryHasAFrenchTranslation() throws {
        let strings = try catalog()
        XCTAssertGreaterThan(strings.count, 100)
        for (key, entry) in strings {
            let value = french(entry)
            XCTAssertNotNil(value, "no French translation for: \(key)")
            XCTAssertFalse(value?.isEmpty ?? true, "empty French translation for: \(key)")
            XCTAssertEqual(key.components(separatedBy: "%@").count, (value ?? "").components(separatedBy: "%@").count,
                           "placeholder mismatch for: \(key)")
        }
    }

    func testEveryStringUsedByTheAppIsInTheCatalog() throws {
        let strings = try catalog()
        let folder = try FileManager.default.contentsOfDirectory(atPath: appFolder.path)
        var used: [String] = []
        for file in folder where file.hasSuffix(".swift") {
            if file == "ErrorTexts.swift" {
                used += try literals(#"^\s+"[a-z_]+": "((?:[^"\\]|\\.)*)",$"#, in: file)
            } else {
                used += try literals(#"\btr\("((?:[^"\\]|\\.)*)"\)"#, in: file)
            }
        }
        XCTAssertGreaterThan(used.count, 100)
        for key in used {
            XCTAssertNotNil(strings[key], "missing from Localizable.xcstrings: \(key)")
        }
    }
}
