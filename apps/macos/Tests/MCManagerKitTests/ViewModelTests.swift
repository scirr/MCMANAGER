import XCTest
@testable import MCManagerKit

@MainActor
final class ViewModelTests: XCTestCase {
    func testListSelectsActiveServerAndFormatsRam() async {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers", json: Samples.serverList)
        let errors = ErrorReporter()
        let model = ServerListViewModel(client: McClient(transport: transport), errors: errors)
        await model.refresh()
        XCTAssertEqual(model.servers.count, 1)
        XCTAssertEqual(model.selection, "survie")
        XCTAssertNil(errors.current)
        XCTAssertEqual(ServerListViewModel.formatRam(6_291_456), "6.0 GB")
        XCTAssertEqual(ServerListViewModel.formatRam(nil), "-")
    }

    func testListReportsDaemonDown() async {
        let errors = ErrorReporter()
        let model = ServerListViewModel(client: McClient(transport: FakeTransport()), errors: errors)
        await model.refresh()
        XCTAssertEqual(errors.current?.code, "daemon_unreachable")
        XCTAssertTrue(model.servers.isEmpty)
    }

    func testDetailRefreshSetsStateAndButtons() async {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers/survie", json: Samples.serverStopped)
        transport.on("GET", "/v1/servers/survie/players", status: 409, json: Samples.offline)
        let errors = ErrorReporter()
        let model = ServerDetailViewModel(client: McClient(transport: transport), errors: errors, name: "survie")
        await model.refresh()
        XCTAssertEqual(model.state, "stopped")
        XCTAssertEqual(model.version, "Fabric 1.21.1")
        XCTAssertTrue(model.canStart)
        XCTAssertFalse(model.canStop)
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.players.onlineText, "-")
    }

    func testStartThenRefreshShowsRunning() async {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/survie/start", json: #"{"ok":true,"code":"started"}"#)
        transport.on("GET", "/v1/servers/survie", json: Samples.serverRunning)
        transport.on("GET", "/v1/servers/survie/players", json: Samples.players)
        let model = ServerDetailViewModel(client: McClient(transport: transport), errors: ErrorReporter(), name: "survie")
        await model.start()
        XCTAssertEqual(model.state, "running")
        XCTAssertEqual(model.ramText, "2.0 GB")
        XCTAssertTrue(model.canStop)
        XCTAssertTrue(model.canRestart)
        XCTAssertEqual(model.players.onlineText, "2/20")
    }

    func testActionErrorIsReported() async {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/survie/start", status: 409, json: #"{"ok":false,"code":"port_taken","message":"Port in use."}"#)
        transport.on("GET", "/v1/servers/survie", json: Samples.serverStopped)
        transport.on("GET", "/v1/servers/survie/players", status: 409, json: Samples.offline)
        let errors = ErrorReporter()
        let model = ServerDetailViewModel(client: McClient(transport: transport), errors: errors, name: "survie")
        await model.start()
        XCTAssertEqual(errors.current?.code, "port_taken")
        XCTAssertFalse(model.isBusy)
    }

    func testRestartFollowsJobUntilFinished() async {
        let transport = FakeTransport()
        let running = #"{"id":"j1","kind":"restartServer","state":"running","progress":10,"code":null,"result":null}"#
        let done = #"{"id":"j1","kind":"restartServer","state":"succeeded","progress":100,"code":"restarted","result":null}"#
        transport.on("POST", "/v1/servers/survie/restart", status: 202, json: running)
        transport.on("GET", "/v1/jobs/j1", json: running)
        transport.on("GET", "/v1/jobs/j1", json: done)
        transport.on("GET", "/v1/servers/survie", json: Samples.serverRunning)
        transport.on("GET", "/v1/servers/survie/players", json: Samples.players)
        let errors = ErrorReporter()
        let model = ServerDetailViewModel(client: McClient(transport: transport), errors: errors, name: "survie")
        model.jobPollInterval = .milliseconds(1)
        await model.restart()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.state, "running")
        XCTAssertEqual(transport.requests.filter { $0.path == "/v1/jobs/j1" }.count, 2)
    }

    func testFailedJobIsReported() async {
        let transport = FakeTransport()
        let failed = #"{"id":"j2","kind":"restartServer","state":"failed","code":"start_failed","result":{"ok":false,"code":"start_failed","message":"Did not start."}}"#
        transport.on("POST", "/v1/servers/survie/restart", status: 202, json: failed)
        transport.on("GET", "/v1/servers/survie", json: Samples.serverRunning)
        transport.on("GET", "/v1/servers/survie/players", json: Samples.players)
        let errors = ErrorReporter()
        let model = ServerDetailViewModel(client: McClient(transport: transport), errors: errors, name: "survie")
        await model.restart()
        XCTAssertEqual(errors.current?.code, "start_failed")
        XCTAssertEqual(errors.current?.message, "Did not start.")
    }

    func testConsoleStreamsAndSends() async {
        let transport = FakeTransport()
        transport.onStream("/v1/servers/survie/console?tail=200", chunks: ["event: line\ndata: hello\n\n", "event: line\ndata: world\n\n"])
        transport.on("POST", "/v1/servers/survie/console", json: #"{"ok":true,"code":"command","output":"a\r\nb"}"#)
        let model = ConsoleViewModel(client: McClient(transport: transport), errors: ErrorReporter(), server: "survie")
        model.start()
        await model.completion?.value
        XCTAssertEqual(model.lines, ["hello", "world"])
        XCTAssertFalse(model.isStreaming)
        model.commandText = "  list "
        await model.send()
        XCTAssertEqual(model.lines.suffix(3), ["> list", "a", "b"])
        XCTAssertEqual(model.commandText, "")
    }

    func testConsoleKeepsOnlyLastLines() async {
        let transport = FakeTransport()
        let chunk = (0..<(ConsoleViewModel.maxLines + 5)).map { "event: line\ndata: l\($0)\n\n" }.joined()
        transport.onStream("/v1/servers/survie/console?tail=200", chunks: [chunk])
        let model = ConsoleViewModel(client: McClient(transport: transport), errors: ErrorReporter(), server: "survie")
        model.start()
        await model.completion?.value
        XCTAssertEqual(model.lines.count, ConsoleViewModel.maxLines)
        XCTAssertEqual(model.lines.first, "l5")
    }

    func testPlayersForbiddenWriteTurnsTheListsReadOnly() async {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers/survie/kick", status: 403, json: #"{"ok":false,"code":"forbidden","message":"No."}"#)
        let errors = ErrorReporter()
        let model = PlayersViewModel(client: McClient(transport: transport), errors: errors, server: "survie")
        XCTAssertFalse(model.isReadOnly)
        await model.kick("Steve")
        XCTAssertTrue(model.isReadOnly)
        XCTAssertEqual(errors.current?.code, "forbidden")
    }

    func testPlayersAddRemoveAndKick() async {
        let transport = FakeTransport()
        transport.on("GET", "/v1/servers/survie/lists/whitelist", json: #"{"ok":true,"entries":[]}"#)
        transport.on("GET", "/v1/servers/survie/lists/whitelist", json: #"{"ok":true,"entries":[{"name":"Steve"}]}"#)
        transport.on("POST", "/v1/servers/survie/lists/whitelist", json: #"{"ok":true,"code":"added"}"#)
        transport.on("DELETE", "/v1/servers/survie/lists/whitelist/Steve", json: #"{"ok":true,"code":"removed"}"#)
        transport.on("POST", "/v1/servers/survie/kick", json: #"{"ok":true,"code":"kicked"}"#)
        transport.on("GET", "/v1/servers/survie/players", json: Samples.players)
        let model = PlayersViewModel(client: McClient(transport: transport), errors: ErrorReporter(), server: "survie")
        await model.loadList()
        XCTAssertTrue(model.entries.isEmpty)
        model.newSubject = " Steve "
        await model.add()
        XCTAssertEqual(model.entries.map(\.subject), ["Steve"])
        XCTAssertEqual(model.newSubject, "")
        await model.remove("Steve")
        XCTAssertTrue(transport.requests.contains { $0.method == "DELETE" })
        await model.kick("Alex")
        XCTAssertEqual(model.online, ["Steve", "Alex"])
    }
}
