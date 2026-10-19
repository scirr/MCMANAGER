import XCTest
@testable import MCManagerKit

private let pin = String(repeating: "AB:", count: 31) + "AB"

final class FakePairing: PairingProtocol, @unchecked Sendable {
    var fingerprint = pin
    var failure: ApiError?
    private(set) var paired: [(host: String, port: Int, code: String, name: String)] = []

    func fetchFingerprint(host: String, port: Int) async throws -> String {
        if let failure { throw failure }
        return fingerprint
    }

    func pair(host: String, port: Int, fingerprint: String, code: String, name: String) async throws -> RemoteProfile {
        if let failure { throw failure }
        paired.append((host, port, code, name))
        return RemoteProfile(name: name, host: host, port: port, fingerprint: fingerprint, deviceId: "d_1", token: "mcm_secret")
    }
}

final class FingerprintTests: XCTestCase {
    func testKnownVector() {
        XCTAssertEqual(
            Fingerprint.format(Data("abc".utf8)),
            "BA:78:16:BF:8F:01:CF:EA:41:41:40:DE:5D:AE:22:23:B0:03:61:A3:96:17:7A:9C:B4:10:FF:61:F2:00:15:AD")
    }

    func testValidity() {
        XCTAssertTrue(Fingerprint.isValid(pin))
        XCTAssertTrue(Fingerprint.isValid(pin.lowercased()))
        XCTAssertFalse(Fingerprint.isValid(nil))
        XCTAssertFalse(Fingerprint.isValid(""))
        XCTAssertFalse(Fingerprint.isValid(String(pin.dropLast())))
        XCTAssertFalse(Fingerprint.isValid(pin.replacingOccurrences(of: "AB", with: "ZZ")))
        XCTAssertFalse(Fingerprint.isValid(pin.replacingOccurrences(of: ":", with: "-")))
    }

    func testEqualityIsCaseInsensitiveAndStrict() {
        XCTAssertTrue(Fingerprint.equal(pin, pin.lowercased()))
        XCTAssertFalse(Fingerprint.equal(pin, String(repeating: "AB:", count: 31) + "AC"))
        XCTAssertFalse(Fingerprint.equal(pin, String(pin.dropLast())))
        XCTAssertFalse(Fingerprint.equal(nil, pin))
    }

    func testPinnedCertificateDecision() {
        let der = Data("certificate".utf8)
        let good = Fingerprint.format(der)
        XCTAssertTrue(Fingerprint.accepts(pinned: good, presentedDER: der))
        XCTAssertTrue(Fingerprint.accepts(pinned: good.lowercased(), presentedDER: der))
        XCTAssertFalse(Fingerprint.accepts(pinned: good, presentedDER: Data("other".utf8)))
        XCTAssertFalse(Fingerprint.accepts(pinned: good, presentedDER: nil))
        XCTAssertFalse(Fingerprint.accepts(pinned: nil, presentedDER: der))
        XCTAssertFalse(Fingerprint.accepts(pinned: "not a fingerprint", presentedDER: der))
    }

    func testHostPort() {
        XCTAssertEqual(HostPort.parse("example.org:8443")?.host, "example.org")
        XCTAssertEqual(HostPort.parse(" 10.0.0.2:8443 ")?.port, 8443)
        XCTAssertEqual(HostPort.parse("[::1]:9000")?.host, "::1")
        XCTAssertNil(HostPort.parse("example.org"))
        XCTAssertNil(HostPort.parse(":8443"))
        XCTAssertNil(HostPort.parse("host:0"))
        XCTAssertNil(HostPort.parse("host:70000"))
        XCTAssertNil(HostPort.parse("ho st:80"))
    }
}

final class RemoteTransportTests: XCTestCase {
    func testRefusesWithoutPinOrToken() {
        XCTAssertThrowsError(try RemoteTransport(host: "h", port: 1, fingerprint: "", token: "t")) { error in
            XCTAssertEqual((error as? ApiError)?.code, "fingerprint_missing")
        }
        XCTAssertThrowsError(try RemoteTransport(host: "h", port: 1, fingerprint: pin, token: "")) { error in
            XCTAssertEqual((error as? ApiError)?.code, "fingerprint_missing")
        }
        XCTAssertNoThrow(try RemoteTransport(host: "h", port: 1, fingerprint: pin, token: "", allowAnonymous: true))
    }

    func testRequestsAreHttpsWithBearerToken() throws {
        let transport = try RemoteTransport(host: "mc.example.org", port: 8443, fingerprint: pin, token: "tok")
        var request = HTTPRequest(method: "POST", path: "/v1/servers/a%20b/start?x=1")
        request.body = Data("{}".utf8)
        let built = try transport.urlRequest(request)
        XCTAssertEqual(built.url?.absoluteString, "https://mc.example.org:8443/v1/servers/a%20b/start?x=1")
        XCTAssertEqual(built.value(forHTTPHeaderField: "Authorization"), "Bearer tok")
        XCTAssertEqual(built.httpMethod, "POST")
    }

    func testAnonymousRequestHasNoAuthorization() throws {
        let transport = try RemoteTransport(host: "h", port: 1, fingerprint: pin, token: "", allowAnonymous: true)
        let built = try transport.urlRequest(HTTPRequest(method: "POST", path: "/v1/pair"))
        XCTAssertNil(built.value(forHTTPHeaderField: "Authorization"))
    }
}

final class ProfileStoreTests: XCTestCase {
    private func tempFile() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("mcm-tests-" + UUID().uuidString, isDirectory: true)
            .appendingPathComponent("remotes.json")
    }

    func testTokenGoesToSecretStoreNotToFile() throws {
        let file = tempFile()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let secrets = MemorySecretStore()
        let store = ProfileStore(fileURL: file, secrets: secrets)
        XCTAssertTrue(store.add(RemoteProfile(name: "home", host: "h", port: 8443, fingerprint: pin, deviceId: "d1", token: "tok-123")))
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("tok-123"))
        XCTAssertTrue(text.contains("\"host\""))
        XCTAssertEqual(secrets.read("home"), "tok-123")
        let loaded = store.load()
        XCTAssertEqual(loaded.count, 1)
        XCTAssertEqual(loaded[0].token, "tok-123")
        XCTAssertEqual(loaded[0].fingerprint, pin)
        XCTAssertEqual(loaded[0].deviceId, "d1")
    }

    func testAddReplacesSameNameAndRemoveForgetsSecret() {
        let file = tempFile()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let secrets = MemorySecretStore()
        let store = ProfileStore(fileURL: file, secrets: secrets)
        store.add(RemoteProfile(name: "a", host: "h1", port: 1, fingerprint: pin, token: "t1"))
        store.add(RemoteProfile(name: "a", host: "h2", port: 2, fingerprint: pin, token: "t2"))
        store.add(RemoteProfile(name: "b", host: "h3", port: 3, fingerprint: pin, token: "t3"))
        XCTAssertEqual(store.load().map(\.host), ["h2", "h3"])
        store.remove("a")
        XCTAssertEqual(store.load().map(\.name), ["b"])
        XCTAssertNil(secrets.read("a"))
    }

    func testMissingOrCorruptFileGivesEmptyList() throws {
        let file = tempFile()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let store = ProfileStore(fileURL: file, secrets: MemorySecretStore())
        XCTAssertTrue(store.load().isEmpty)
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: file)
        XCTAssertTrue(store.load().isEmpty)
    }
}

final class PairingClientTests: XCTestCase {
    private func client(_ transport: FakeTransport) -> PairingClient {
        PairingClient(makeTransport: { _, _, _ in transport })
    }

    func testPairBuildsProfile() async throws {
        let transport = FakeTransport()
        transport.on("POST", "/v1/pair", status: 201, json: #"{"ok":true,"device_id":"d_7","token":"mcm_abc","fingerprint":"\#(pin.lowercased())"}"#)
        let profile = try await client(transport).pair(host: "h", port: 8443, fingerprint: pin.lowercased(), code: "12345678", name: "Mac")
        XCTAssertEqual(profile.token, "mcm_abc")
        XCTAssertEqual(profile.deviceId, "d_7")
        XCTAssertEqual(profile.fingerprint, pin)
        XCTAssertEqual(profile.name, "Mac")
        let body = transport.lastBody()
        XCTAssertTrue(body.contains("\"code\":\"12345678\""))
        XCTAssertTrue(body.contains("\"name\":\"Mac\""))
    }

    func testPairRejectsFingerprintReportedDifferently() async {
        let transport = FakeTransport()
        let other = String(repeating: "CD:", count: 31) + "CD"
        transport.on("POST", "/v1/pair", status: 201, json: #"{"ok":true,"device_id":"d","token":"t","fingerprint":"\#(other)"}"#)
        do {
            _ = try await client(transport).pair(host: "h", port: 1, fingerprint: pin, code: "12345678", name: "Mac")
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "fingerprint_mismatch")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testPairSurfacesServerErrors() async {
        let transport = FakeTransport()
        transport.on("POST", "/v1/pair", status: 422, json: #"{"ok":false,"code":"bad_pair_code","message":"Wrong code."}"#)
        do {
            _ = try await client(transport).pair(host: "h", port: 1, fingerprint: pin, code: "00000000", name: "Mac")
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "bad_pair_code")
            XCTAssertEqual(error.status, 422)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testPairRefusesInvalidFingerprint() async {
        do {
            _ = try await client(FakeTransport()).pair(host: "h", port: 1, fingerprint: "nope", code: "12345678", name: "Mac")
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "fingerprint_missing")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testPairWithoutTokenIsBadAnswer() async {
        let transport = FakeTransport()
        transport.on("POST", "/v1/pair", status: 201, json: #"{"ok":true}"#)
        do {
            _ = try await client(transport).pair(host: "h", port: 1, fingerprint: pin, code: "12345678", name: "Mac")
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "bad_answer")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}

@MainActor
final class ConnectionTests: XCTestCase {
    private func make(local: McClientProtocol? = McClient(transport: FakeTransport()),
                      remote: ((RemoteProfile) throws -> McClientProtocol)? = nil)
        -> (ConnectionViewModel, ProfileStore, FakePairing, URL) {
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("mcm-tests-" + UUID().uuidString, isDirectory: true)
            .appendingPathComponent("remotes.json")
        let store = ProfileStore(fileURL: file, secrets: MemorySecretStore())
        let pairing = FakePairing()
        let model = ConnectionViewModel(store: store, pairing: pairing, localName: "This Mac", local: { local }, remote: remote)
        return (model, store, pairing, file.deletingLastPathComponent())
    }

    func testStartsOnLocalMachine() throws {
        let (model, _, _, folder) = make()
        defer { try? FileManager.default.removeItem(at: folder) }
        XCTAssertEqual(model.targets.count, 1)
        XCTAssertTrue(model.selected.isLocal)
        XCTAssertNotNil(try model.makeClient())
    }

    func testLocalMissingGivesNoClient() throws {
        let (model, _, _, folder) = make(local: nil)
        defer { try? FileManager.default.removeItem(at: folder) }
        XCTAssertNil(try model.makeClient())
    }

    func testAddSelectsRemoteAndBuildsRemoteClient() throws {
        var used: [RemoteProfile] = []
        let (model, store, _, folder) = make(remote: { profile in
            used.append(profile)
            return McClient(transport: FakeTransport())
        })
        defer { try? FileManager.default.removeItem(at: folder) }
        XCTAssertTrue(model.addProfile(RemoteProfile(name: "home", host: "h", port: 1, fingerprint: pin, token: "t")))
        XCTAssertEqual(model.targets.map(\.name), ["This Mac", "home"])
        XCTAssertFalse(model.selected.isLocal)
        XCTAssertNotNil(try model.makeClient())
        XCTAssertEqual(used.map(\.token), ["t"])
        XCTAssertEqual(store.load().count, 1)
        model.reload()
        XCTAssertEqual(model.selected.name, "home")
    }

    func testRemoveSelectedFallsBackToLocal() {
        let (model, store, _, folder) = make()
        defer { try? FileManager.default.removeItem(at: folder) }
        model.addProfile(RemoteProfile(name: "home", host: "h", port: 1, fingerprint: pin, token: "t"))
        model.removeSelected()
        XCTAssertTrue(model.selected.isLocal)
        XCTAssertTrue(store.load().isEmpty)
        model.removeSelected()
        XCTAssertEqual(model.targets.count, 1)
    }

    func testApplyNotifies() {
        let (model, _, _, folder) = make()
        defer { try? FileManager.default.removeItem(at: folder) }
        var calls = 0
        model.onChange = { calls += 1 }
        model.apply()
        XCTAssertEqual(calls, 1)
    }

    func testPairingWizardHappyPath() async {
        let (connection, store, pairing, folder) = make()
        defer { try? FileManager.default.removeItem(at: folder) }
        let wizard = PairingWizardViewModel(connection: connection, defaultName: "Mac de Cris")
        XCTAssertEqual(wizard.step, .address)
        wizard.address = "nope"
        await wizard.probe()
        XCTAssertEqual(wizard.errorCode, "bad_address")
        wizard.address = "mc.example.org:8443"
        await wizard.probe()
        XCTAssertEqual(wizard.step, .confirm)
        XCTAssertEqual(wizard.fingerprint, pin)
        wizard.confirmFingerprint()
        XCTAssertEqual(wizard.step, .code)
        wizard.code = "1234"
        wizard.submitCode()
        XCTAssertEqual(wizard.errorCode, "bad_pair_code")
        XCTAssertEqual(wizard.step, .code)
        wizard.code = "12345678"
        wizard.submitCode()
        XCTAssertEqual(wizard.step, .name)
        await wizard.finish()
        XCTAssertEqual(wizard.step, .done)
        XCTAssertEqual(wizard.code, "")
        XCTAssertEqual(pairing.paired.first?.host, "mc.example.org")
        XCTAssertEqual(pairing.paired.first?.name, "Mac de Cris")
        XCTAssertEqual(store.load().first?.token, "mcm_secret")
        XCTAssertEqual(connection.selected.name, "Mac de Cris")
    }

    func testPairingWizardRejectAndFailure() async {
        let (connection, store, pairing, folder) = make()
        defer { try? FileManager.default.removeItem(at: folder) }
        let wizard = PairingWizardViewModel(connection: connection, defaultName: "Mac")
        wizard.address = "h:1"
        await wizard.probe()
        wizard.reject()
        XCTAssertEqual(wizard.step, .address)
        XCTAssertEqual(wizard.fingerprint, "")
        await wizard.probe()
        wizard.confirmFingerprint()
        wizard.code = "12345678"
        wizard.submitCode()
        pairing.failure = ApiError(code: "bad_pair_code", status: 422)
        await wizard.finish()
        XCTAssertEqual(wizard.errorCode, "bad_pair_code")
        XCTAssertEqual(wizard.step, .code)
        XCTAssertEqual(wizard.code, "")
        XCTAssertTrue(store.load().isEmpty)
    }

    func testPairingWizardUnreachable() async {
        let (connection, _, pairing, folder) = make()
        defer { try? FileManager.default.removeItem(at: folder) }
        pairing.failure = ApiError(code: "remote_unreachable")
        let wizard = PairingWizardViewModel(connection: connection, defaultName: "Mac")
        wizard.address = "h:1"
        await wizard.probe()
        XCTAssertEqual(wizard.errorCode, "remote_unreachable")
        XCTAssertEqual(wizard.step, .address)
        XCTAssertFalse(wizard.isBusy)
    }
}
