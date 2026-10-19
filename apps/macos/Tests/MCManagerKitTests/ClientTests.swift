import XCTest
@testable import MCManagerKit

final class ClientTests: XCTestCase {
    func testListServersDecodesSnakeCase() async throws {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers", json: Samples.serverList)
        let servers = try await McClient(transport: transport).listServers()
        XCTAssertEqual(servers.count, 1)
        XCTAssertEqual(servers[0].name, "survie")
        XCTAssertEqual(servers[0].rssKb, 6_291_456)
        XCTAssertEqual(servers[0].uptimeS, 7312)
        XCTAssertEqual(servers[0].state, "running")
    }

    func testOnlinePlayers() async throws {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers/survie/players", json: Samples.players)
        let players = try await McClient(transport: transport).onlinePlayers("survie")
        XCTAssertEqual(players.players, ["Steve", "Alex"])
        XCTAssertEqual(players.max, 20)
    }

    func testErrorBodyBecomesApiError() async {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers/survie", status: 404, json: Samples.notFound)
        do {
            _ = try await McClient(transport: transport).server("survie")
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "not_found")
            XCTAssertEqual(error.status, 404)
            XCTAssertEqual(error.message, "No server matches 'survie'.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testOkFalseOn200IsAnError() async {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers/survie/players", status: 200, json: Samples.offline)
        do {
            _ = try await McClient(transport: transport).onlinePlayers("survie")
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "server_offline")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testTransportFailureIsUnreachable() async {
        do {
            _ = try await McClient(transport: FakeTransport()).listServers()
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "daemon_unreachable")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testMalformedBodyIsBadAnswer() async {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers", json: "not json")
        do {
            _ = try await McClient(transport: transport).listServers()
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "bad_answer")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testServerNameIsEscaped() async throws {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/my%20world/start", json: #"{"ok":true,"code":"started"}"#)
        _ = try await McClient(transport: transport).start("my world")
        XCTAssertEqual(transport.requests.last?.path, "/v1/servers/my%20world/start")
    }

    func testCommandBodyAndOutput() async throws {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/survie/console", json: #"{"ok":true,"code":"command","output":"There are 0 of a max of 20 players online"}"#)
        let reply = try await McClient(transport: transport).sendCommand("survie", command: "list")
        XCTAssertEqual(reply.output, "There are 0 of a max of 20 players online")
        XCTAssertEqual(transport.lastBody(), #"{"command":"list"}"#)
    }

    func testStopWithoutBodyAndWithForce() async throws {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/survie/stop", json: #"{"ok":true,"code":"stopped"}"#)
        let client = McClient(transport: transport)
        _ = try await client.stop("survie", request: nil)
        XCTAssertNil(transport.requests.last?.body)
        _ = try await client.stop("survie", request: StopRequest(force: true))
        XCTAssertEqual(transport.lastBody(), #"{"force":true}"#)
    }

    func testRestartReturnsJob() async throws {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/survie/restart", status: 202, json: """
        {"code":null,"created_at":"2026-10-08T10:00:00Z","id":"j_restartserve","kind":"restartServer","progress":0,"result":null,"server":null,"state":"running","updated_at":"2026-10-08T10:00:00Z"}
        """)
        let job = try await McClient(transport: transport).restart("survie")
        XCTAssertEqual(job.id, "j_restartserve")
        XCTAssertFalse(job.isFinished)
    }

    func testPlayerListEntries() async throws {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers/survie/lists/ban", json: """
        {"ok":true,"code":"list","server":"survie","entries":[{"name":"Griefer","reason":"grief"},{"ip":"10.0.0.1"}]}
        """)
        let listing = try await McClient(transport: transport).playerList("survie", kind: "ban")
        XCTAssertEqual(listing.entries.map(\.subject), ["Griefer", "10.0.0.1"])
    }

    func testConsoleStreamParsesEvents() async throws {
        let transport = FakeTransport()
        transport.onStream("/v1/servers/survie/console?tail=200", chunks: [
            ": keepalive\n\nevent: line\nda",
            "ta: [10:00:31] Done\n\nevent: line\r\ndata: second\r\n\r\n",
        ])
        var received: [ConsoleEvent] = []
        for try await event in McClient(transport: transport).streamConsole("survie", tail: 200) {
            received.append(event)
        }
        XCTAssertEqual(received.map(\.data), ["[10:00:31] Done", "second"])
        XCTAssertEqual(received.first?.name, "line")
    }

    func testConsoleStreamErrorIsThrown() async {
        let transport = FakeTransport()
        do {
            for try await _ in McClient(transport: transport).streamConsole("survie", tail: 5) {}
            XCTFail("expected an error")
        } catch let error as ApiError {
            XCTAssertEqual(error.code, "not_found")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testSSEParserMultilineData() {
        var parser = SSEParser()
        let events = parser.feed(Data("id: 7\nevent: line\ndata: a\ndata: b\n\n".utf8))
        XCTAssertEqual(events, [ConsoleEvent(id: "7", name: "line", data: "a\nb")])
    }

    func testLocatorPrefersExplicitFolder() {
        let folders = ApiLocator.runFolders(environment: ["MCMANAGER_RUN_DIR": "/tmp/run"], home: "/Users/x")
        XCTAssertEqual(folders.first, "/tmp/run")
        XCTAssertTrue(folders.contains("/Users/x/Library/Application Support/MCManager/run"))
        let path = ApiLocator.socketPath(runFolders: ["/a", "/b"], fileExists: { $0 == "/b/api.sock" })
        XCTAssertEqual(path, "/b/api.sock")
        XCTAssertNil(ApiLocator.socketPath(runFolders: ["/a"], fileExists: { _ in false }))
    }
}
