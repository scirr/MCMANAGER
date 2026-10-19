import Foundation
import Observation

public struct ConnectionTarget: Equatable, Identifiable, Sendable {
    public let name: String
    public let profile: RemoteProfile?
    public var id: String { profile == nil ? "" : "remote:" + name }
    public var isLocal: Bool { profile == nil }
}

@MainActor
@Observable
public final class ConnectionViewModel {
    public private(set) var targets: [ConnectionTarget] = []
    public var selectedID = ""
    public var onChange: (() -> Void)?

    @ObservationIgnored private let store: ProfileStore
    @ObservationIgnored public let pairing: PairingProtocol
    @ObservationIgnored private let localName: String
    @ObservationIgnored private let local: () -> McClientProtocol?
    @ObservationIgnored private let remote: (RemoteProfile) throws -> McClientProtocol

    public init(store: ProfileStore, pairing: PairingProtocol, localName: String,
                local: @escaping () -> McClientProtocol?,
                remote: ((RemoteProfile) throws -> McClientProtocol)? = nil) {
        self.store = store
        self.pairing = pairing
        self.localName = localName
        self.local = local
        self.remote = remote ?? { profile in try McClient(transport: RemoteTransport(profile: profile)) }
        reload()
    }

    public var selected: ConnectionTarget {
        targets.first { $0.id == selectedID } ?? ConnectionTarget(name: localName, profile: nil)
    }

    public func reload() {
        var built = [ConnectionTarget(name: localName, profile: nil)]
        for profile in store.load() {
            built.append(ConnectionTarget(name: profile.name, profile: profile))
        }
        targets = built
        if !built.contains(where: { $0.id == selectedID }) { selectedID = "" }
    }

    public func makeClient() throws -> McClientProtocol? {
        if let profile = selected.profile { return try remote(profile) }
        return local()
    }

    public func apply() { onChange?() }

    @discardableResult
    public func addProfile(_ profile: RemoteProfile) -> Bool {
        guard store.add(profile) else {
            errors?.show("keychain_failed")
            return false
        }
        reload()
        selectedID = "remote:" + profile.name
        return true
    }

    public func removeSelected() {
        guard let profile = selected.profile else { return }
        store.remove(profile.name)
        selectedID = ""
        reload()
    }

    @ObservationIgnored public var errors: ErrorReporter?
}

public enum PairingStep: Equatable, Sendable {
    case address, confirm, code, name, done
}

@MainActor
@Observable
public final class PairingWizardViewModel {
    public private(set) var step = PairingStep.address
    public var address = ""
    public private(set) var fingerprint = ""
    public var code = ""
    public var deviceName: String
    public private(set) var errorCode = ""
    public private(set) var isBusy = false

    @ObservationIgnored private let connection: ConnectionViewModel
    @ObservationIgnored private var host = ""
    @ObservationIgnored private var port = 0

    public init(connection: ConnectionViewModel, defaultName: String) {
        self.connection = connection
        deviceName = defaultName
    }

    public static func isCode(_ value: String) -> Bool {
        value.count == 8 && value.allSatisfy { $0.isASCII && $0.isNumber }
    }

    public func probe() async {
        errorCode = ""
        guard let parsed = HostPort.parse(address) else {
            errorCode = "bad_address"
            return
        }
        host = parsed.host
        port = parsed.port
        await run {
            fingerprint = try await connection.pairing.fetchFingerprint(host: host, port: port)
            step = .confirm
        }
    }

    public func confirmFingerprint() {
        if step == .confirm && !fingerprint.isEmpty { step = .code }
    }

    public func reject() {
        fingerprint = ""
        code = ""
        step = .address
    }

    public func submitCode() {
        errorCode = ""
        guard step == .code else { return }
        guard Self.isCode(code) else {
            errorCode = "bad_pair_code"
            return
        }
        step = .name
    }

    public func finish() async {
        errorCode = ""
        let name = deviceName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            errorCode = "bad_name"
            return
        }
        await run({
            let profile = try await connection.pairing.pair(host: host, port: port, fingerprint: fingerprint,
                                                            code: code, name: name)
            code = ""
            if connection.addProfile(profile) {
                step = .done
            } else {
                errorCode = "keychain_failed"
            }
        }, onApiError: {
            self.code = ""
            self.step = .code
        })
    }

    private func run(_ work: () async throws -> Void, onApiError: (() -> Void)? = nil) async {
        isBusy = true
        defer { isBusy = false }
        do {
            try await work()
        } catch let error as ApiError {
            errorCode = error.code
            onApiError?()
        } catch {
            errorCode = "remote_unreachable"
        }
    }
}
