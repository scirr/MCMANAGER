import Foundation
import Observation

@MainActor
@Observable
public final class CreateServerViewModel {
    public static let loaders = ["Paper", "Purpur", "Spigot", "Folia", "Fabric", "Forge", "NeoForge", "Vanilla", "Velocity"]
    public static let lastStep = 2

    public private(set) var step = 0
    public var name = ""
    public var loader = "Paper"
    public var version = ""
    public var ram = "4G"
    public var port = ""
    public var rconPort = ""
    public var acceptEula = false
    public var modpack = ""
    public private(set) var pack: ModpackInfo?
    public private(set) var createdName = ""
    public let tab: TabRunner

    @ObservationIgnored private let client: McClientProtocol
    @ObservationIgnored private let errors: ErrorReporter

    public init(client: McClientProtocol, errors: ErrorReporter) {
        self.client = client
        self.errors = errors
        tab = TabRunner(client: client, errors: errors, server: "")
    }

    public var canBack: Bool { step > 0 && !tab.isBusy }
    public var canNext: Bool { step < Self.lastStep }
    public var isLastStep: Bool { step == Self.lastStep }
    public var canCreate: Bool { isLastStep && acceptEula && !tab.isBusy }
    public var isProxy: Bool { loader == "Velocity" }
    public var isModpack: Bool { !modpack.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    static func ramIsValid(_ text: String) -> Bool {
        guard let unit = text.last, "GgMm".contains(unit) else { return false }
        let digits = text.dropLast()
        return !digits.isEmpty && digits.allSatisfy { $0.isASCII && $0.isNumber } && digits.first != "0"
    }

    static func portIsValid(_ text: String) -> Bool {
        text.isEmpty || (Int(text).map { (1024...65535).contains($0) } ?? false)
    }

    private func validate(_ step: Int) -> String? {
        if step == 0 {
            return name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isModpack ? "name_required" : nil
        }
        if step == 1 {
            if !Self.ramIsValid(ram.trimmingCharacters(in: .whitespaces)) { return "invalid_ram" }
            let portText = port.trimmingCharacters(in: .whitespaces)
            let rconText = rconPort.trimmingCharacters(in: .whitespaces)
            if !Self.portIsValid(portText) || !Self.portIsValid(rconText) { return "invalid_port" }
        }
        return nil
    }

    public func next() {
        guard step < Self.lastStep else { return }
        if let problem = validate(step) {
            errors.show(problem)
            return
        }
        step += 1
    }

    public func back() {
        if step > 0 { step -= 1 }
    }

    public func lookupModpack() async {
        let source = modpack.trimmingCharacters(in: .whitespacesAndNewlines)
        pack = nil
        guard !source.isEmpty else {
            errors.show("source_required")
            return
        }
        await tab.write { self.pack = try await self.client.modpackInfo(source: source) }
    }

    public func create() async {
        guard isLastStep, acceptEula else { return }
        for index in 0..<Self.lastStep {
            if let problem = validate(index) {
                step = index
                errors.show(problem)
                return
            }
        }
        if isModpack {
            await createModpack()
            return
        }
        let versionText = version.trimmingCharacters(in: .whitespaces)
        let portText = port.trimmingCharacters(in: .whitespaces)
        let rconText = rconPort.trimmingCharacters(in: .whitespaces)
        let request = CreateServerRequest(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines), loader: loader, acceptEula: true,
            version: versionText.isEmpty || isProxy ? nil : versionText,
            ram: ram.trimmingCharacters(in: .whitespaces).uppercased(),
            port: Int(portText), rconPort: Int(rconText))
        let done = await tab.runJob("create") { try await self.client.createServer(request) }
        if done { createdName = request.name }
    }

    private func createModpack() async {
        let source = modpack.trimmingCharacters(in: .whitespacesAndNewlines)
        let typedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let portText = port.trimmingCharacters(in: .whitespaces)
        let rconText = rconPort.trimmingCharacters(in: .whitespaces)
        let request = ModpackInstallRequest(
            source: source, acceptEula: true, name: typedName.isEmpty ? nil : typedName,
            ram: ram.trimmingCharacters(in: .whitespaces).uppercased(),
            port: Int(portText), rconPort: Int(rconText))
        let done = await tab.runJob("create") { try await self.client.installModpack(request) }
        guard done else { return }
        let job = tab.lastJob
        let created = job?.result?.server ?? job?.server ?? typedName
        createdName = created.isEmpty ? (pack?.title ?? source) : created
    }
}
