import XCTest
@testable import MCManagerKit

@MainActor
final class HostTests: XCTestCase {
    private func make() -> (FakeTransport, ErrorReporter, McClient) {
        let transport = FakeTransport()
        return (transport, ErrorReporter(), McClient(transport: transport))
    }

    private func job(_ id: String, state: String, result: String = "null") -> String {
        #"{"id":"\#(id)","kind":"k","state":"\#(state)","progress":100,"code":null,"result":\#(result)}"#
    }

    private func body(_ transport: FakeTransport, _ method: String, _ path: String) -> String {
        let request = transport.requests.first { $0.method == method && $0.path == path }
        return String(decoding: request?.body ?? Data(), as: UTF8.self)
    }

    private let channels = """
    {"ok":true,"channels":[{"name":"ntfy","type":"ntfy","events":["crash","backup_failed"],"topic":"mc","secrets_set":["token"]},\
    {"name":"discord","type":"discord","events":["*"],"legacy":true}]}
    """

    func testAlertsRows() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/a/alerts", json: channels)
        let model = AlertsViewModel(client: client, errors: errors, server: "a")
        await model.refresh()
        XCTAssertEqual(model.rows.map(\.name), ["ntfy", "discord"])
        XCTAssertEqual(model.rows[0].target, "mc")
        XCTAssertEqual(model.rows[0].events, ["crash", "backup_failed"])
        XCTAssertTrue(model.rows[1].legacy)
    }

    func testAlertAddSendsFieldsOfTheTypeOnly() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/a/alerts", status: 201, json: #"{"ok":true,"channel":"mine"}"#)
        transport.on("GET", "/v1/servers/a/alerts", json: channels)
        let model = AlertsViewModel(client: client, errors: errors, server: "a")
        model.newType = "email"
        model.values = ["host": "smtp.x", "port": "2525", "password": "pw", "sender": "a@x", "to": "b@x", "token": "ignored"]
        model.selectedEvents = ["crash", "backup_failed"]
        model.channelName = " mine "
        await model.add()
        XCTAssertNil(errors.current)
        let sent = body(transport, "POST", "/v1/servers/a/alerts")
        XCTAssertTrue(sent.contains("\"type\":\"email\""))
        XCTAssertTrue(sent.contains("\"port\":2525"))
        XCTAssertTrue(sent.contains("\"password\":\"pw\""))
        XCTAssertTrue(sent.contains("\"events\":\"crash,backup_failed\""))
        XCTAssertTrue(sent.contains("\"name\":\"mine\""))
        XCTAssertFalse(sent.contains("ignored"))
        XCTAssertTrue(model.values.isEmpty)
        XCTAssertEqual(model.tab.lastDone, "alert_added")
        XCTAssertEqual(model.rows.count, 2)
    }

    func testAlertAddRefusesBadPort() async {
        let (transport, errors, client) = make()
        let model = AlertsViewModel(client: client, errors: errors, server: "a")
        model.newType = "email"
        model.values = ["port": "99999"]
        await model.add()
        XCTAssertEqual(errors.current?.code, "bad_port")
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testAlertTestFailureNamesTheChannel() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/a/alerts/test", json: #"{"ok":false,"code":"alert_test_failed","failed":"ntfy","checks":[]}"#)
        let model = AlertsViewModel(client: client, errors: errors, server: "a")
        await model.test(nil)
        XCTAssertEqual(errors.current?.code, "alert_test_failed")
        XCTAssertEqual(errors.current?.message, "ntfy")
    }

    func testAlertRemoveNeedsConfirmation() async {
        let (transport, errors, client) = make()
        transport.on("DELETE", "/v1/servers/a/alerts/ntfy", json: #"{"ok":true,"channel":"ntfy"}"#)
        transport.on("GET", "/v1/servers/a/alerts", json: channels)
        let model = AlertsViewModel(client: client, errors: errors, server: "a")
        await model.remove("ntfy", confirmed: false)
        XCTAssertTrue(transport.requests.isEmpty)
        await model.remove("ntfy", confirmed: true)
        XCTAssertEqual(model.tab.lastDone, "alert_removed")
    }

    func testAlertsForbiddenHidesActions() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/a/alerts", status: 403, json: #"{"ok":false,"code":"forbidden","message":"No."}"#)
        let model = AlertsViewModel(client: client, errors: errors, server: "a")
        await model.refresh()
        XCTAssertNil(errors.current)
        XCTAssertTrue(model.tab.isDenied)
        XCTAssertFalse(model.tab.canAct)
    }

    func testJavaRowsAndInstall() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/java", json: """
        {"ok":true,"runtimes":{"17":"/j/17","21":"/j/21"},"servers":[{"server":"a","java":21,"minecraft":"1.21"}]}
        """)
        transport.on("PUT", "/v1/java/25", status: 202, json: job("j1", state: "succeeded"))
        let model = JavaViewModel(client: client, errors: errors)
        await model.refresh()
        XCTAssertEqual(model.rows.map(\.major), ["17", "21"])
        XCTAssertEqual(model.rows[1].servers, ["a"])
        XCTAssertEqual(model.installable, ["8", "11", "25"])
        await model.install("25")
        XCTAssertEqual(model.tab.lastDone, "java_installed")
        await model.install("3")
        XCTAssertEqual(errors.current?.code, "java_unknown_version")
    }

    func testJavaRemoveNeedsConfirmation() async {
        let (transport, errors, client) = make()
        transport.on("DELETE", "/v1/java/17", json: #"{"ok":true,"major":17}"#)
        transport.on("GET", "/v1/java", json: #"{"ok":true,"runtimes":{},"servers":[]}"#)
        let model = JavaViewModel(client: client, errors: errors)
        await model.remove("17", confirmed: false)
        XCTAssertTrue(transport.requests.isEmpty)
        await model.remove("17", confirmed: true)
        XCTAssertEqual(model.tab.lastDone, "java_removed")
    }

    private func routeDevices(_ transport: FakeTransport) {
        transport.on("GET", "/v1/devices", json: """
        {"ok":true,"devices":[{"id":"d1","name":"Phone","roles":{"default":"operator"},"last_seen":"2026-10-28T10:00:00","last_ip":"1.2.3.4","revoked":false},\
        {"id":"d2","name":"Old","roles":{"default":"viewer"},"revoked":true}]}
        """)
        transport.on("GET", "/v1/remote", json: #"{"ok":true,"enabled":true,"bind":"0.0.0.0:8443","fingerprint":"AA:BB"}"#)
        transport.on("GET", "/v1/audit?limit=50", json: """
        {"ok":true,"entries":[{"at":"2026-10-28T10:00:00","action":"start","device":"Phone","server":"a","ok":false,"result":"forbidden"}]}
        """)
    }

    func testDevicesLoad() async {
        let (transport, errors, client) = make()
        routeDevices(transport)
        let model = DevicesViewModel(client: client, errors: errors)
        await model.refresh()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.devices.map(\.name), ["Phone"])
        XCTAssertEqual(model.devices[0].role, "operator")
        XCTAssertEqual(model.devices[0].lastSeen, "2026-10-28 10:00:00")
        XCTAssertTrue(model.remoteEnabled)
        XCTAssertEqual(model.fingerprint, "AA:BB")
        XCTAssertEqual(model.audit.count, 1)
        XCTAssertFalse(model.audit[0].ok)
    }

    func testDevicesDeniedForNonAdmin() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/devices", status: 403, json: #"{"ok":false,"code":"forbidden"}"#)
        let model = DevicesViewModel(client: client, errors: errors)
        await model.refresh()
        XCTAssertNil(errors.current)
        XCTAssertTrue(model.tab.isDenied)
        XCTAssertTrue(transport.requests.allSatisfy { $0.path == "/v1/devices" })
    }

    func testPairingCode() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/pair/codes", status: 201, json: #"{"ok":true,"pairing_code":"12345678","expires_in_s":300,"role":"viewer"}"#)
        let model = DevicesViewModel(client: client, errors: errors)
        model.codeName = " Tablet "
        model.codeRole = "viewer"
        await model.newCode()
        XCTAssertEqual(model.code, PairingCodeInfo(code: "12345678", minutes: 5))
        let sent = body(transport, "POST", "/v1/pair/codes")
        XCTAssertTrue(sent.contains("\"name\":\"Tablet\""))
        XCTAssertTrue(sent.contains("\"role\":\"viewer\""))
    }

    func testLocalOnlyCommandsAreHiddenAfterForbidden() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/pair/codes", status: 403, json: #"{"ok":false,"code":"forbidden"}"#)
        let model = DevicesViewModel(client: client, errors: errors)
        await model.newCode()
        XCTAssertTrue(model.localOnlyDenied)
        XCTAssertFalse(model.tab.isReadOnly)
        XCTAssertNil(model.code)
    }

    func testRemoteToggleAndRole() async {
        let (transport, errors, client) = make()
        routeDevices(transport)
        transport.on("PUT", "/v1/remote", json: #"{"ok":true,"enabled":false}"#)
        transport.on("PUT", "/v1/devices/d1/roles", json: #"{"ok":true}"#)
        let model = DevicesViewModel(client: client, errors: errors)
        await model.refresh()
        await model.setRemote(true)
        XCTAssertNil(transport.requests.first { $0.method == "PUT" && $0.path == "/v1/remote" })
        await model.setRemote(false)
        XCTAssertTrue(body(transport, "PUT", "/v1/remote").contains("\"enabled\":false"))
        await model.setRole("d1", role: "root")
        XCTAssertNil(transport.requests.first { $0.path == "/v1/devices/d1/roles" })
        await model.setRole("d1", role: "admin")
        XCTAssertEqual(body(transport, "PUT", "/v1/devices/d1/roles"), #"{"roles":{"default":"admin"}}"#)
    }

    func testRevokeNeedsConfirmation() async {
        let (transport, errors, client) = make()
        routeDevices(transport)
        transport.on("DELETE", "/v1/devices/d1", json: #"{"ok":true,"id":"d1"}"#)
        let model = DevicesViewModel(client: client, errors: errors)
        await model.revoke("d1", confirmed: false)
        XCTAssertNil(transport.requests.first { $0.method == "DELETE" })
        await model.revoke("d1", confirmed: true)
        XCTAssertEqual(model.tab.lastDone, "device_revoked")
    }

    func testUpdateCheckApplyAndRollback() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/update", json: #"{"ok":true,"current":"3.0.0","latest":"3.0.1","update_available":true,"rollback_available":true}"#)
        transport.on("POST", "/v1/update", status: 202, json: job("u1", state: "succeeded"))
        transport.on("POST", "/v1/update/rollback", json: #"{"ok":true,"version":"3.0.0"}"#)
        let model = UpdateViewModel(client: client, errors: errors)
        await model.refresh()
        XCTAssertTrue(model.available)
        XCTAssertEqual(model.latest, "3.0.1")
        await model.apply(confirmed: false)
        XCTAssertNil(transport.requests.first { $0.method == "POST" })
        await model.apply(confirmed: true)
        XCTAssertEqual(model.tab.lastDone, "update_done")
        await model.rollback(confirmed: true)
        XCTAssertEqual(model.tab.lastDone, "update_rolled_back")
    }

    func testUpdateWithoutNewVersionDoesNothing() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/update", json: #"{"ok":true,"current":"3.0.0","latest":"3.0.0","update_available":false,"rollback_available":false}"#)
        let model = UpdateViewModel(client: client, errors: errors)
        await model.refresh()
        await model.apply(confirmed: true)
        await model.rollback(confirmed: true)
        XCTAssertEqual(transport.requests.count, 1)
    }

    func testDoctorAcceptsReportWithErrors() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/doctor", json: """
        {"ok":false,"code":"doctor","errors":1,"warnings":1,"has_issues":true,"checks":[\
        {"server":null,"name":"java","ok":true,"level":"ok","detail":"21","fix":null},\
        {"server":"a","name":"port","ok":false,"level":"err","detail":"taken","fix":"change it"}]}
        """)
        let model = DoctorViewModel(client: client, errors: errors)
        await model.run()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.checks.count, 2)
        XCTAssertEqual(model.checks[1].fix, "change it")
        XCTAssertEqual(model.errorCount, 1)
        XCTAssertEqual(model.summary, "errors")
        XCTAssertFalse(model.tab.isBusy)
    }

    private func routerJSON(enabled: Bool = true, routes: String = #"{"b.example.com":"b","a.example.com":"a"}"#) -> String {
        """
        {"ok":true,"config":{"enabled":\(enabled),"port":25565,"default":"a","routes":\(routes),"allow":["10.0.0.0/8"],"deny":[]},\
        "pending_restart":["a"]}
        """
    }

    private func routeRouter(_ transport: FakeTransport) {
        transport.on("GET", "/v1/router", json: routerJSON())
        transport.on("GET", "/v1/servers", json: Samples.serverList)
    }

    func testRouterLoad() async {
        let (transport, errors, client) = make()
        routeRouter(transport)
        let model = RouterViewModel(client: client, errors: errors)
        await model.refresh()
        XCTAssertNil(errors.current)
        XCTAssertTrue(model.enabled)
        XCTAssertEqual(model.defaultServer, "a")
        XCTAssertEqual(model.routes.map(\.host), ["a.example.com", "b.example.com"])
        XCTAssertEqual(model.allow, ["10.0.0.0/8"])
        XCTAssertEqual(model.pending, ["a"])
        XCTAssertEqual(model.servers, ["survie"])
    }

    func testRouterRouteKeepsUnderscoresInHostNames() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/router", json: routerJSON(routes: #"{"my_host.example.com":"a"}"#))
        transport.on("GET", "/v1/servers", json: Samples.serverList)
        let model = RouterViewModel(client: client, errors: errors)
        await model.refresh()
        XCTAssertEqual(model.routes.map(\.host), ["my_host.example.com"])
    }

    func testRouterChanges() async {
        let (transport, errors, client) = make()
        routeRouter(transport)
        transport.on("PUT", "/v1/router/routes/new.example.com", json: routerJSON())
        transport.on("DELETE", "/v1/router/routes/a.example.com", json: routerJSON(routes: "{}"))
        transport.on("POST", "/v1/router/disable", json: routerJSON(enabled: false))
        transport.on("POST", "/v1/router/access", json: routerJSON())
        let model = RouterViewModel(client: client, errors: errors)
        await model.refresh()
        model.newHost = " New.Example.com "
        model.newServer = "survie"
        await model.addRoute()
        XCTAssertEqual(body(transport, "PUT", "/v1/router/routes/new.example.com"), #"{"server":"survie"}"#)
        XCTAssertEqual(model.tab.lastDone, "route_saved")
        XCTAssertTrue(model.newHost.isEmpty)
        await model.removeRoute("a.example.com", confirmed: false)
        XCTAssertNil(transport.requests.first { $0.method == "DELETE" })
        await model.removeRoute("a.example.com", confirmed: true)
        XCTAssertTrue(model.routes.isEmpty)
        await model.toggle(false)
        XCTAssertFalse(model.enabled)
        await model.editAccess(list: "deny", action: "add", cidr: " 1.2.3.0/24 ")
        let access = body(transport, "POST", "/v1/router/access")
        XCTAssertTrue(access.contains("\"list\":\"deny\""))
        XCTAssertTrue(access.contains("\"action\":\"add\""))
        XCTAssertTrue(access.contains("1.2.3.0"))
    }

    func testRouterRefusesUnknownServer() async {
        let (transport, errors, client) = make()
        routeRouter(transport)
        let model = RouterViewModel(client: client, errors: errors)
        await model.refresh()
        model.newHost = "x.example.com"
        model.newServer = "nope"
        await model.addRoute()
        XCTAssertEqual(errors.current?.code, "invalid_value")
        XCTAssertNil(transport.requests.first { $0.method == "PUT" })
    }

    func testModpackLookupAndCreate() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/modpacks/info?source=Cool%20Pack", json: """
        {"ok":true,"title":"Cool Pack","version":"1.2","mc_version":"1.21.1","loader":"neoforge"}
        """)
        transport.on("POST", "/v1/modpacks", status: 202, json: job("m1", state: "succeeded", result: #"{"ok":true,"server":"cool"}"#))
        let model = CreateServerViewModel(client: client, errors: errors)
        model.tab.jobPollInterval = .milliseconds(1)
        model.modpack = " Cool Pack "
        await model.lookupModpack()
        XCTAssertEqual(model.pack?.title, "Cool Pack")
        XCTAssertEqual(model.pack?.mcVersion, "1.21.1")
        model.next()
        XCTAssertNil(errors.current)
        model.next()
        model.acceptEula = true
        await model.create()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.createdName, "cool")
        let sent = body(transport, "POST", "/v1/modpacks")
        XCTAssertTrue(sent.contains("\"source\":\"Cool Pack\""))
        XCTAssertTrue(sent.contains("\"accept_eula\":true"))
        XCTAssertFalse(sent.contains("\"name\""))
    }

    func testModpackLookupNeedsASource() async {
        let (transport, errors, client) = make()
        let model = CreateServerViewModel(client: client, errors: errors)
        await model.lookupModpack()
        XCTAssertEqual(errors.current?.code, "source_required")
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testModpackUpdateReportsUpToDate() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/modpack/update", status: 202,
                     json: job("m2", state: "succeeded", result: #"{"ok":true,"code":"pack_up_to_date"}"#))
        transport.on("GET", "/v1/servers/survie/mods", json: #"{"ok":true,"mods":[]}"#)
        let model = ModsViewModel(client: client, errors: errors, server: "survie")
        model.tab.jobPollInterval = .milliseconds(1)
        await model.updateModpack()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.tab.lastDone, "modpack_current")
        XCTAssertFalse(model.tab.restartRequired)
    }

    func testModpackUpdateRequiresRestart() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/modpack/update", status: 202,
                     json: job("m3", state: "succeeded", result: #"{"ok":true,"code":"modpack_updated"}"#))
        transport.on("GET", "/v1/servers/survie/mods", json: #"{"ok":true,"mods":[]}"#)
        let model = ModsViewModel(client: client, errors: errors, server: "survie")
        model.tab.jobPollInterval = .milliseconds(1)
        await model.updateModpack()
        XCTAssertEqual(model.tab.lastDone, "modpack_updated")
        XCTAssertTrue(model.tab.restartRequired)
    }

    private func prefs() -> NotificationPrefs {
        NotificationPrefs(defaults: UserDefaults(suiteName: "mcmanager-test-" + UUID().uuidString)!)
    }

    private func event(_ name: String, _ data: String) -> ConsoleEvent {
        ConsoleEvent(name: name, data: data)
    }

    func testNoticesFollowThePreferences() {
        let prefs = prefs()
        let crash = event("alert", #"{"type":"alert","server":"a","event":"crash","detail":"exit 1"}"#)
        let loop = event("alert", #"{"type":"alert","server":"a","event":"crash_loop"}"#)
        let failed = event("alert", #"{"type":"alert","server":"a","event":"backup_failed"}"#)
        let stopped = event("alert", #"{"type":"alert","server":"a","event":"stop"}"#)
        let joined = event("players", #"{"type":"players","server":"a","online":1,"players":["Steve"],"joined":["Steve"],"left":[]}"#)
        let left = event("players", #"{"type":"players","server":"a","online":0,"players":[],"joined":[],"left":["Steve"]}"#)
        XCTAssertEqual(prefs.notice(for: crash), AppNotice(kind: "crash", server: "a", detail: "exit 1"))
        XCTAssertEqual(prefs.notice(for: loop)?.kind, "crash_loop")
        XCTAssertEqual(prefs.notice(for: failed)?.kind, "backup_failed")
        XCTAssertEqual(prefs.notice(for: joined)?.detail, "Steve")
        XCTAssertNil(prefs.notice(for: stopped))
        XCTAssertNil(prefs.notice(for: left))
        XCTAssertNil(prefs.notice(for: event("state", "not json")))
        prefs.set("crash", false)
        XCTAssertNil(prefs.notice(for: crash))
        XCTAssertNil(prefs.notice(for: loop))
        XCTAssertNotNil(prefs.notice(for: failed))
    }

    func testPreferencesAreSaved() {
        let suite = "mcmanager-test-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        let first = NotificationPrefs(defaults: defaults)
        XCTAssertTrue(first.isEnabled("join"))
        first.set("join", false)
        first.set("unknown", true)
        let second = NotificationPrefs(defaults: defaults)
        XCTAssertFalse(second.isEnabled("join"))
        XCTAssertTrue(second.isEnabled("crash"))
        XCTAssertFalse(second.isEnabled("unknown"))
    }

    func testWatcherDeliversStreamedEvents() async {
        let (transport, _, client) = make()
        transport.onStream("/v1/events", chunks: [
            "event: state\ndata: {\"type\":\"state\",\"server\":\"a\",\"state\":\"running\"}\n\n",
            "event: alert\ndata: {\"type\":\"alert\",\"server\":\"a\",\"event\":\"crash\"}\n\n",
            "event: players\ndata: {\"type\":\"players\",\"server\":\"a\",\"joined\":[\"Alex\"]}\n\n",
        ])
        var received: [AppNotice] = []
        let watcher = EventWatcher(client: client, prefs: prefs()) { received.append($0) }
        await watcher.consume()
        XCTAssertEqual(received.map(\.kind), ["crash", "join"])
        XCTAssertEqual(received[1].detail, "Alex")
    }

    func testWatcherSurvivesAFailingStream() async {
        let (_, _, client) = make()
        var received: [AppNotice] = []
        let watcher = EventWatcher(client: client, prefs: prefs()) { received.append($0) }
        await watcher.consume()
        XCTAssertTrue(received.isEmpty)
    }
}
