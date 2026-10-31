import XCTest
@testable import MCManagerKit

@MainActor
final class TabsTests: XCTestCase {
    private func make() -> (FakeTransport, ErrorReporter, McClient) {
        let transport = FakeTransport()
        return (transport, ErrorReporter(), McClient(transport: transport))
    }

    private func job(_ id: String, state: String, progress: Int = 0, code: String? = nil, result: String = "null") -> String {
        let codeText = code.map { "\"\($0)\"" } ?? "null"
        return #"{"id":"\#(id)","kind":"k","state":"\#(state)","progress":\#(progress),"code":\#(codeText),"result":\#(result)}"#
    }

    func testBackupsRefreshFormatsEntries() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/survie/backups", json: """
        {"ok":true,"backups":[{"created":"2026-10-08T12:00:03","created_ts":1791460803,"encrypted":true,\
        "file":"a.zip","id":"survie_midi","size":1288490188,"type":"midi"}]}
        """)
        let model = BackupsViewModel(client: client, errors: errors, server: "survie")
        await model.refresh()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.items.count, 1)
        XCTAssertEqual(model.items[0].date, "2026-10-08 12:00:03")
        XCTAssertEqual(model.items[0].sizeText, "1.2 GB")
        XCTAssertEqual(model.items[0].origin, "midi")
        XCTAssertTrue(model.items[0].encrypted)
        XCTAssertFalse(model.isEmpty)
    }

    func testBackupCreateFollowsJobAndRefreshes() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/backups", status: 202, json: job("j1", state: "running"))
        transport.on("GET", "/v1/jobs/j1", json: job("j1", state: "running", progress: 40))
        transport.on("GET", "/v1/jobs/j1", json: job("j1", state: "succeeded", progress: 100))
        transport.on("GET", "/v1/servers/survie/backups", json: #"{"ok":true,"backups":[]}"#)
        let model = BackupsViewModel(client: client, errors: errors, server: "survie")
        model.tab.jobPollInterval = .milliseconds(1)
        await model.create()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.tab.lastDone, "create")
        XCTAssertFalse(model.tab.isBusy)
        XCTAssertEqual(transport.requests.filter { $0.path == "/v1/jobs/j1" }.count, 2)
        XCTAssertTrue(transport.requests.contains { $0.method == "GET" && $0.path.hasSuffix("/backups") })
    }

    func testRestoreNeedsConfirmation() async {
        let (transport, errors, client) = make()
        let model = BackupsViewModel(client: client, errors: errors, server: "survie")
        await model.restore("b1", confirmed: false)
        await model.restore(nil, confirmed: true)
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testRestoreSendsConfirmation() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/backups/b%201/restore", status: 202, json: job("j2", state: "succeeded", progress: 100))
        transport.on("GET", "/v1/servers/survie/backups", json: #"{"ok":true,"backups":[]}"#)
        let model = BackupsViewModel(client: client, errors: errors, server: "survie")
        await model.restore("b 1", confirmed: true)
        XCTAssertNil(errors.current)
        XCTAssertTrue(transport.requests.contains { $0.path == "/v1/servers/survie/backups/b%201/restore" && String(decoding: $0.body ?? Data(), as: UTF8.self).contains("\"confirm\":true") })
        XCTAssertEqual(model.tab.lastDone, "restore")
    }

    func testForbiddenMakesTabReadOnly() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/backups", status: 403, json: #"{"ok":false,"code":"forbidden","message":"No."}"#)
        transport.on("GET", "/v1/servers/survie/backups", json: #"{"ok":true,"backups":[]}"#)
        let model = BackupsViewModel(client: client, errors: errors, server: "survie")
        await model.create()
        XCTAssertEqual(errors.current?.code, "forbidden")
        XCTAssertTrue(model.tab.isReadOnly)
        XCTAssertFalse(model.tab.canAct)
    }

    func testFailedJobIsReported() async {
        let (transport, errors, client) = make()
        let failed = job("j3", state: "failed", code: "backup_failed", result: #"{"ok":false,"code":"backup_failed","message":"Disk full."}"#)
        transport.on("POST", "/v1/servers/survie/backups", status: 202, json: failed)
        transport.on("GET", "/v1/servers/survie/backups", json: #"{"ok":true,"backups":[]}"#)
        let model = BackupsViewModel(client: client, errors: errors, server: "survie")
        await model.create()
        XCTAssertEqual(errors.current?.code, "backup_failed")
        XCTAssertEqual(model.tab.lastDone, "")
    }

    func testModsAddRemoveAndUpdate() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/survie/mods", json: """
        {"ok":true,"mods":[{"file":"sodium.jar","id":"sodium","name":"Sodium","version":"0.6","source":"modrinth",\
        "adds_blocks":false,"modpack":true},{"file":"decor.jar","id":"decor","adds_blocks":true}]}
        """)
        transport.on("POST", "/v1/servers/survie/mods", status: 202, json: job("m1", state: "succeeded", progress: 100))
        transport.on("POST", "/v1/servers/survie/mods/update", status: 202, json: job("m2", state: "succeeded", progress: 100))
        transport.on("DELETE", "/v1/servers/survie/mods/decor.jar?confirm_blocks=true", json: #"{"ok":true,"file":"decor.jar","restart_required":true}"#)
        let model = ModsViewModel(client: client, errors: errors, server: "survie")
        await model.refresh()
        XCTAssertEqual(model.items.map(\.name), ["Sodium", "decor"])
        XCTAssertTrue(model.items[1].addsBlocks)
        XCTAssertTrue(model.items[0].inModpack)

        model.newReference = " lithium "
        await model.add()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.newReference, "")
        XCTAssertTrue(model.tab.restartRequired)
        let body = String(decoding: transport.requests.first { $0.method == "POST" && $0.path.hasSuffix("/mods") }?.body ?? Data(), as: UTF8.self)
        XCTAssertTrue(body.contains("\"ref\":\"lithium\""))
        XCTAssertFalse(body.contains("source"))

        await model.updateAll()
        XCTAssertNil(errors.current)

        await model.remove("decor.jar", confirmed: false)
        XCTAssertFalse(transport.requests.contains { $0.method == "DELETE" })
        await model.remove("decor.jar", confirmed: true)
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.tab.lastDone, "remove")
    }

    func testModAddUsesChosenSource() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/mods", status: 202, json: job("m1", state: "succeeded", progress: 100))
        transport.on("GET", "/v1/servers/survie/mods", json: #"{"ok":true,"mods":[]}"#)
        let model = ModsViewModel(client: client, errors: errors, server: "survie")
        model.newReference = "x"
        model.selectedSource = "hangar"
        await model.add()
        XCTAssertTrue(transport.lastBodyOf("POST", "/v1/servers/survie/mods").contains("\"source\":\"hangar\""))
    }

    func testDatapacksToggle() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/survie/datapacks", json: """
        {"ok":true,"running":true,"packs":[{"id":"vein","file":"vein.zip","enabled":true,"worldgen":false},\
        {"id":"odd","file":"odd","enabled":false,"problem":"nested"}]}
        """)
        transport.on("PUT", "/v1/servers/survie/datapacks/vein.zip", json: #"{"ok":true,"pack":"vein.zip","restart_required":true}"#)
        let model = DatapacksViewModel(client: client, errors: errors, server: "survie")
        await model.refresh()
        XCTAssertTrue(model.serverRunning)
        XCTAssertEqual(model.items.map(\.canToggle), [true, false])
        XCTAssertEqual(model.items[1].problem, "nested")
        await model.setEnabled("vein.zip", enabled: false)
        XCTAssertNil(errors.current)
        XCTAssertTrue(model.tab.restartRequired)
        XCTAssertFalse(model.tab.isBusy)
        XCTAssertTrue(transport.lastBodyOf("PUT", "/v1/servers/survie/datapacks/vein.zip").contains("\"enabled\":false"))
    }

    func testWorldRefreshAndPregenOffline() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/survie/worlds", json: """
        {"ok":true,"level":"world","size_bytes":3221225472,"dimensions":[{"id":"overworld","size_bytes":2147483648}]}
        """)
        transport.on("GET", "/v1/servers/survie/worlds/pregen", status: 409, json: #"{"ok":false,"code":"pregen_offline","message":"Offline."}"#)
        let model = WorldViewModel(client: client, errors: errors, server: "survie")
        await model.refresh()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.totalSizeText, "3.0 GB")
        XCTAssertEqual(model.dimensions.map(\.sizeText), ["2.0 GB"])
        XCTAssertEqual(model.pregenText, "")
    }

    func testPregenValidationAndStart() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/worlds/pregen", status: 202, json: #"{"ok":true,"radius":2000,"progress":"0%"}"#)
        let model = WorldViewModel(client: client, errors: errors, server: "survie")
        model.radiusText = "abc"
        await model.startPregen()
        XCTAssertEqual(errors.current?.code, "invalid_radius")
        XCTAssertTrue(transport.requests.isEmpty)
        errors.dismiss()
        model.radiusText = "2000"
        model.centerText = " 0,0 "
        await model.startPregen()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.pregenText, "0%")
        let body = transport.lastBodyOf("POST", "/v1/servers/survie/worlds/pregen")
        XCTAssertTrue(body.contains("\"radius\":2000"))
        XCTAssertTrue(body.contains("\"center\":\"0,0\""))
    }

    func testResetNeedsConfirmationAndFlagsOverworld() async {
        let (transport, errors, client) = make()
        transport.on("POST", "/v1/servers/survie/worlds/overworld/reset", status: 202, json: job("w1", state: "succeeded", progress: 100))
        transport.on("GET", "/v1/servers/survie/worlds", json: #"{"ok":true,"size_bytes":0,"dimensions":[]}"#)
        transport.on("GET", "/v1/servers/survie/worlds/pregen", json: #"{"ok":true,"progress":""}"#)
        let model = WorldViewModel(client: client, errors: errors, server: "survie")
        await model.reset("overworld", confirmed: false)
        XCTAssertTrue(transport.requests.isEmpty)
        await model.reset("overworld", confirmed: true)
        XCTAssertNil(errors.current)
        let body = transport.lastBodyOf("POST", "/v1/servers/survie/worlds/overworld/reset")
        XCTAssertTrue(body.contains("\"confirmed\":true"))
        XCTAssertTrue(body.contains("\"include_overworld\":true"))
    }

    func testTasksRefreshCreateToggleDeleteRun() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/survie/tasks", json: """
        {"ok":true,"tasks":[{"id":3,"name":"nuit","cron":"0 4 * * *","action":"restart","enabled":true,"warn":[300,45],\
        "last_run":"2026-10-08T04:00:00","next_run":"2026-10-09T04:00:00","last_result":{"ok":false,"code":"task_error"}}]}
        """)
        transport.on("POST", "/v1/servers/survie/tasks", status: 201, json: #"{"ok":true,"task":{"id":4}}"#)
        transport.on("PATCH", "/v1/servers/survie/tasks/3", json: #"{"ok":true,"task":{"id":3}}"#)
        transport.on("DELETE", "/v1/servers/survie/tasks/3", json: #"{"ok":true}"#)
        transport.on("POST", "/v1/servers/survie/tasks/3/run", status: 202, json: job("t1", state: "succeeded", progress: 100))
        let model = TasksViewModel(client: client, errors: errors, server: "survie")
        await model.refresh()
        XCTAssertEqual(model.items[0].warnText, "5m, 45s")
        XCTAssertEqual(model.items[0].nextRun, "2026-10-09 04:00:00")
        XCTAssertEqual(model.items[0].lastResult, "task_error")

        await model.create()
        XCTAssertEqual(errors.current?.code, "cron_required")
        errors.dismiss()
        model.newAction = "command"
        model.newCron = "*/5 * * * *"
        await model.create()
        XCTAssertEqual(errors.current?.code, "command_required")
        errors.dismiss()
        model.newCommand = "save-all"
        model.newWarn = "5m"
        await model.create()
        XCTAssertNil(errors.current)
        let body = transport.lastBodyOf("POST", "/v1/servers/survie/tasks")
        XCTAssertTrue(body.contains("\"command\":\"save-all\""))
        XCTAssertFalse(body.contains("warn"))
        XCTAssertEqual(model.newCron, "")

        await model.setEnabled(3, enabled: false)
        XCTAssertTrue(transport.lastBodyOf("PATCH", "/v1/servers/survie/tasks/3").contains("\"enabled\":false"))
        await model.delete(3, confirmed: false)
        XCTAssertFalse(transport.requests.contains { $0.method == "DELETE" })
        await model.delete(3, confirmed: true)
        XCTAssertTrue(transport.requests.contains { $0.method == "DELETE" })
        await model.run(3)
        XCTAssertEqual(model.tab.lastDone, "run")
        XCTAssertNil(errors.current)
    }

    func testTaskWarnOnlyForRestartAndStop() {
        let (_, errors, client) = make()
        let model = TasksViewModel(client: client, errors: errors, server: "survie")
        XCTAssertTrue(model.allowsWarn)
        model.newAction = "backup"
        XCTAssertFalse(model.allowsWarn)
        XCTAssertFalse(model.needsCommand)
        model.newAction = "command"
        XCTAssertTrue(model.needsCommand)
        XCTAssertEqual(TasksViewModel.formatWarn(120), "2m")
    }

    private let configJSON = """
    {"ok":true,"config":{"nom_serveur":"survie","port":25565,"heure_ouverture":7,"minute_ouverture":30,\
    "heure_fermeture":23,"minute_fermeture":0,"sleep_freeze":true,"domaine":null},"secrets_set":["mcrcon_pass"]}
    """

    private func settingsModel(_ transport: FakeTransport, _ errors: ErrorReporter) -> SettingsViewModel {
        transport.on("GET", "/v1/servers/survie/config", json: configJSON)
        transport.on("GET", "/v1/servers/survie", json: #"{"name":"survie","mode":"always-on","state":"running"}"#)
        transport.on("GET", "/v1/servers/survie/sleep", json: """
        {"ok":true,"code":"sleep_status","enabled":false,"after_s":7200,"allow":[],"join_mode":"kick",\
        "hold_timeout_s":120,"freeze":false,"state":"running"}
        """)
        transport.on("GET", "/v1/servers/survie/java", json: """
        {"ok":true,"runtimes":{"21":"/j/21","17":"/j/17"},"servers":[{"java":21,"minecraft":"1.21.1","server":"survie"}]}
        """)
        return SettingsViewModel(client: McClient(transport: transport), errors: errors, server: "survie")
    }

    func testSettingsRefreshHidesSecrets() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        await model.refresh()
        XCTAssertNil(errors.current)
        let byKey = Dictionary(uniqueKeysWithValues: model.items.map { ($0.key, $0) })
        XCTAssertEqual(byKey["nom_serveur"]?.value, "survie")
        XCTAssertEqual(byKey["port"]?.value, "25565")
        XCTAssertNil(byKey["sleep_freeze"])
        XCTAssertNil(byKey["sleep_join_mode"])
        XCTAssertEqual(byKey["domaine"]?.value, "")
        XCTAssertEqual(byKey["mcrcon_pass"]?.isSecret, true)
        XCTAssertEqual(byKey["mcrcon_pass"]?.isSet, true)
        XCTAssertEqual(byKey["mcrcon_pass"]?.value, "")
        XCTAssertEqual(byKey["webhook_url"]?.isSet, false)
        XCTAssertEqual(byKey["cpu_affinity"]?.value, "")
        XCTAssertEqual(byKey["internal_port"]?.isChanged, false)
        XCTAssertEqual(model.openTime, "07:30")
        XCTAssertEqual(model.closeTime, "23:00")
        XCTAssertEqual(model.mode, "always-on")
        XCTAssertEqual(model.javaChoices, ["system", "17", "21"])
        XCTAssertEqual(model.javaChoice, "21")
    }

    func testSettingsSaveSendsOnlyChangedValues() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        transport.on("PUT", "/v1/servers/survie/config/port", json: #"{"ok":true,"key":"port","restart_required":true}"#)
        transport.on("PUT", "/v1/servers/survie/config/mcrcon_pass", json: #"{"ok":true,"key":"mcrcon_pass","restart_required":false}"#)
        await model.refresh()
        await model.save()
        XCTAssertFalse(transport.requests.contains { $0.method == "PUT" })
        model.items.first { $0.key == "port" }?.value = " 25570 "
        model.items.first { $0.key == "mcrcon_pass" }?.value = "s3cret"
        await model.save()
        XCTAssertNil(errors.current)
        XCTAssertTrue(model.tab.restartRequired)
        XCTAssertEqual(model.tab.lastDone, "save")
        XCTAssertTrue(transport.lastBodyOf("PUT", "/v1/servers/survie/config/port").contains("\"value\":\"25570\""))
        XCTAssertTrue(transport.lastBodyOf("PUT", "/v1/servers/survie/config/mcrcon_pass").contains("\"value\":\"s3cret\""))
    }

    func testSettingsModeScheduleAndJava() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        transport.on("PUT", "/v1/servers/survie/mode", json: #"{"ok":true,"code":"mode_set","mode":"maintenance"}"#)
        transport.on("PUT", "/v1/servers/survie/schedule", json: #"{"ok":true,"code":"schedule_set"}"#)
        transport.on("PUT", "/v1/servers/survie/java", json: #"{"ok":true,"restart_required":true}"#)
        await model.refresh()
        await model.setMode("bogus")
        await model.setMode("always-on")
        XCTAssertFalse(transport.requests.contains { $0.method == "PUT" })
        await model.setMode("maintenance")
        XCTAssertEqual(model.mode, "maintenance")

        model.openTime = "25:00"
        await model.saveSchedule()
        XCTAssertEqual(errors.current?.code, "invalid_time")
        errors.dismiss()
        model.openTime = "6:05"
        model.closeTime = "22:30"
        await model.saveSchedule()
        XCTAssertNil(errors.current)
        let schedule = transport.lastBodyOf("PUT", "/v1/servers/survie/schedule")
        XCTAssertTrue(schedule.contains("\"open_hour\":6"))
        XCTAssertTrue(schedule.contains("\"close_minute\":30"))

        await model.saveJava()
        XCTAssertFalse(transport.requests.contains { $0.method == "PUT" && $0.path.hasSuffix("/java") })
        model.javaChoice = "17"
        await model.saveJava()
        XCTAssertTrue(model.tab.restartRequired)
        XCTAssertTrue(transport.lastBodyOf("PUT", "/v1/servers/survie/java").contains("\"choice\":\"17\""))
    }

    func testSettingsOfferKnownKeysAbsentFromTheConfig() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        transport.on("PUT", "/v1/servers/survie/config/internal_port", json: #"{"ok":true,"key":"internal_port","restart_required":true}"#)
        await model.refresh()
        let absent = model.items.first { $0.key == "internal_port" }
        XCTAssertEqual(absent?.value, "")
        absent?.value = "25570"
        await model.save()
        XCTAssertNil(errors.current)
        XCTAssertEqual(transport.requests.filter { $0.method == "PUT" }.map(\.path), ["/v1/servers/survie/config/internal_port"])
    }

    func testSleepIsLoadedInMinutesAndSendsOnlyWhatChanged() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        transport.on("PUT", "/v1/servers/survie/sleep", json: """
        {"ok":true,"code":"sleep_updated","enabled":true,"after_s":1800,"allow":[],"join_mode":"kick","hold_timeout_s":120,\
        "freeze":false,"notes":[]}
        """)
        await model.refresh()
        XCTAssertFalse(model.sleepEnabled)
        XCTAssertEqual(model.sleepMinutes, "120")
        XCTAssertEqual(model.sleepJoinMode, "kick")
        XCTAssertTrue(model.sleepFreezeSupported)
        model.sleepEnabled = true
        model.sleepMinutes = " 30 "
        await model.saveSleep()
        XCTAssertNil(errors.current)
        let body = transport.lastBodyOf("PUT", "/v1/servers/survie/sleep")
        XCTAssertTrue(body.contains("\"enabled\":true"))
        XCTAssertTrue(body.contains("\"after_s\":1800"))
        XCTAssertFalse(body.contains("join_mode"))
        XCTAssertFalse(body.contains("freeze"))
        XCTAssertEqual(model.tab.lastDone, "sleep")
        XCTAssertFalse(model.tab.restartRequired)
        XCTAssertEqual(model.sleepMinutes, "30")
    }

    func testSleepSendsJoinModeAndFreezeWhenChanged() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        transport.on("PUT", "/v1/servers/survie/sleep", json: """
        {"ok":true,"code":"sleep_updated","enabled":false,"after_s":7200,"allow":[],"join_mode":"hold","hold_timeout_s":120,\
        "freeze":true,"notes":["Restart the server to apply the hold mode."]}
        """)
        await model.refresh()
        model.sleepJoinMode = "hold"
        model.sleepFreeze = true
        await model.saveSleep()
        let body = transport.lastBodyOf("PUT", "/v1/servers/survie/sleep")
        XCTAssertTrue(body.contains("\"join_mode\":\"hold\""))
        XCTAssertTrue(body.contains("\"freeze\":true"))
        XCTAssertTrue(model.tab.restartRequired)
    }

    func testSleepSettingsSayWhenFreezingIsImpossible() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let json = #"{"enabled":false,"after_s":7200,"freeze":false,"freeze_supported":false}"#
        let sleep = try decoder.decode(SleepSettings.self, from: Data(json.utf8))
        XCTAssertEqual(sleep.freezeSupported, false)
    }

    func testSleepRejectsABadDelayBeforeCalling() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        await model.refresh()
        model.sleepMinutes = "4"
        await model.saveSleep()
        XCTAssertEqual(errors.current?.code, "sleep_after_too_short")
        errors.dismiss()
        model.sleepMinutes = "abc"
        await model.saveSleep()
        XCTAssertEqual(errors.current?.code, "invalid_value")
        XCTAssertFalse(transport.requests.contains { $0.method == "PUT" })
    }

    func testSleepFreezeRefusedOnAWindowsServerIsReportedByCode() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        let model = settingsModel(transport, errors)
        transport.on("PUT", "/v1/servers/survie/sleep", status: 501,
                     json: #"{"ok":false,"code":"unsupported_on_windows","message":"No."}"#)
        await model.refresh()
        model.sleepFreeze = true
        await model.saveSleep()
        XCTAssertEqual(errors.current?.code, "unsupported_on_windows")
        XCTAssertEqual(model.tab.lastDone, "")
    }

    func testDatapackPlacementIsSentOnlyWhenEnabling() async {
        let (transport, errors, client) = make()
        transport.on("GET", "/v1/servers/survie/datapacks", json: """
        {"ok":true,"running":true,"packs":[{"id":"vein","file":"vein.zip","enabled":false,"worldgen":false}]}
        """)
        transport.on("PUT", "/v1/servers/survie/datapacks/vein.zip", json: #"{"ok":true,"pack":"vein.zip","restart_required":false}"#)
        let model = DatapacksViewModel(client: client, errors: errors, server: "survie")
        await model.refresh()
        await model.setEnabled("vein.zip", enabled: true)
        XCTAssertFalse(transport.lastBodyOf("PUT", "/v1/servers/survie/datapacks/vein.zip").contains("first"))
        model.placement = "first"
        await model.setEnabled("vein.zip", enabled: true)
        XCTAssertTrue(transport.lastBodyOf("PUT", "/v1/servers/survie/datapacks/vein.zip").contains("\"first\":true"))
        model.placement = "before_vanilla"
        await model.setEnabled("vein.zip", enabled: true)
        XCTAssertTrue(transport.lastBodyOf("PUT", "/v1/servers/survie/datapacks/vein.zip").contains("\"before_vanilla\":true"))
        await model.setEnabled("vein.zip", enabled: false)
        XCTAssertEqual(transport.lastBodyOf("PUT", "/v1/servers/survie/datapacks/vein.zip"), #"{"enabled":false}"#)
    }

    func testClockParsing() {
        XCTAssertEqual(SettingsViewModel.parseClock("07:05")?.hour, 7)
        XCTAssertEqual(SettingsViewModel.parseClock(" 23:59 ")?.minute, 59)
        XCTAssertNil(SettingsViewModel.parseClock("24:00"))
        XCTAssertNil(SettingsViewModel.parseClock("7"))
        XCTAssertNil(SettingsViewModel.parseClock("a:b"))
        XCTAssertEqual(SettingsViewModel.clock(7, 5), "07:05")
    }

    func testWizardValidatesAndCreates() async {
        let transport = FakeTransport()
        let errors = ErrorReporter()
        transport.on("POST", "/v1/servers", status: 202, json: job("c1", state: "running"))
        transport.on("GET", "/v1/jobs/c1", json: job("c1", state: "succeeded", progress: 100))
        let model = CreateServerViewModel(client: McClient(transport: transport), errors: errors)
        model.tab.jobPollInterval = .milliseconds(1)
        model.next()
        XCTAssertEqual(errors.current?.code, "name_required")
        XCTAssertEqual(model.step, 0)
        errors.dismiss()
        model.name = " Survie "
        model.next()
        XCTAssertEqual(model.step, 1)
        model.ram = "lots"
        model.next()
        XCTAssertEqual(errors.current?.code, "invalid_ram")
        errors.dismiss()
        model.ram = "4g"
        model.port = "80"
        model.next()
        XCTAssertEqual(errors.current?.code, "invalid_port")
        errors.dismiss()
        model.port = "25570"
        model.next()
        XCTAssertEqual(model.step, 2)
        XCTAssertFalse(model.canCreate)
        await model.create()
        XCTAssertTrue(transport.requests.isEmpty)
        model.acceptEula = true
        XCTAssertTrue(model.canCreate)
        await model.create()
        XCTAssertNil(errors.current)
        XCTAssertEqual(model.createdName, "Survie")
        let body = transport.lastBodyOf("POST", "/v1/servers")
        XCTAssertTrue(body.contains("\"name\":\"Survie\""))
        XCTAssertTrue(body.contains("\"accept_eula\":true"))
        XCTAssertTrue(body.contains("\"ram\":\"4G\""))
        XCTAssertTrue(body.contains("\"port\":25570"))
        XCTAssertFalse(body.contains("rcon_port"))
        XCTAssertFalse(body.contains("\"version\""))
        model.back()
        XCTAssertEqual(model.step, 1)
    }

    func testWizardProxyHasNoVersion() async {
        let transport = FakeTransport()
        transport.on("POST", "/v1/servers", status: 202, json: job("c2", state: "succeeded", progress: 100))
        let model = CreateServerViewModel(client: McClient(transport: transport), errors: ErrorReporter())
        model.name = "edge"
        model.loader = "Velocity"
        model.version = "1.21"
        model.next()
        model.next()
        model.acceptEula = true
        await model.create()
        XCTAssertEqual(model.createdName, "edge")
        XCTAssertFalse(transport.lastBodyOf("POST", "/v1/servers").contains("\"version\""))
    }

    func testFormatSize() {
        XCTAssertEqual(TabRunner.formatSize(512), "512 B")
        XCTAssertEqual(TabRunner.formatSize(2048), "2.0 KB")
        XCTAssertEqual(TabRunner.formatSize(nil), "-")
    }

    func testDetailOwnsTabs() async {
        let transport = FakeTransport()
        let model = ServerDetailViewModel(client: McClient(transport: transport), errors: ErrorReporter(), name: "survie")
        XCTAssertEqual(model.backups.tab.server, "survie")
        XCTAssertEqual(model.settings.tab.server, "survie")
    }
}

extension FakeTransport {
    func lastBodyOf(_ method: String, _ path: String) -> String {
        let match = requests.last { $0.method == method && $0.path == path }
        return String(decoding: match?.body ?? Data(), as: UTF8.self)
    }
}
