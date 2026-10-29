import Foundation

public protocol McClientProtocol: Sendable {
    func listServers() async throws -> [ServerSnapshot]
    func server(_ name: String) async throws -> ServerSnapshot
    func start(_ name: String) async throws -> OperationResult
    func stop(_ name: String, request: StopRequest?) async throws -> OperationResult
    func restart(_ name: String) async throws -> Job
    func resume(_ name: String) async throws -> OperationResult
    func sendCommand(_ name: String, command: String) async throws -> OperationResult
    func streamConsole(_ name: String, tail: Int) -> AsyncThrowingStream<ConsoleEvent, Error>
    func onlinePlayers(_ name: String) async throws -> PlayersOnline
    func playerList(_ name: String, kind: String) async throws -> PlayerListing
    func addToList(_ name: String, kind: String, subject: String, reason: String?) async throws -> OperationResult
    func removeFromList(_ name: String, kind: String, subject: String) async throws -> OperationResult
    func kick(_ name: String, player: String, reason: String?) async throws -> OperationResult
    func job(_ id: String) async throws -> Job
    func listBackups(_ name: String) async throws -> [BackupEntry]
    func createBackup(_ name: String) async throws -> Job
    func restoreBackup(_ name: String, backup: String, confirm: Bool) async throws -> Job
    func listMods(_ name: String) async throws -> [ModEntry]
    func addMod(_ name: String, reference: String, source: String?) async throws -> Job
    func removeMod(_ name: String, mod: String, confirmBlocks: Bool) async throws -> ModRemoved
    func updateMods(_ name: String, mod: String?) async throws -> Job
    func listDatapacks(_ name: String) async throws -> DatapackList
    func setDatapackEnabled(_ name: String, pack: String, enabled: Bool, placement: String?) async throws -> DatapackSet
    func listWorlds(_ name: String) async throws -> WorldList
    func pregenStatus(_ name: String) async throws -> PregenProgress
    func startPregen(_ name: String, radius: Int, center: String?) async throws -> Pregen
    func resetDimension(_ name: String, dimension: String, confirmed: Bool, includeOverworld: Bool) async throws -> Job
    func listTasks(_ name: String) async throws -> [TaskEntry]
    func createTask(_ name: String, request: TaskCreateRequest) async throws -> TaskCreated
    func updateTask(_ name: String, task: Int, enabled: Bool) async throws -> TaskCreated
    func deleteTask(_ name: String, task: Int) async throws -> TaskCreated
    func runTask(_ name: String, task: Int, skipWarn: Bool) async throws -> Job
    func serverConfig(_ name: String) async throws -> ConfigDocument
    func setConfigValue(_ name: String, key: String, value: String) async throws -> ConfigSet
    func setMode(_ name: String, mode: String) async throws -> OperationResult
    func setSchedule(_ name: String, schedule: ScheduleRequest) async throws -> OperationResult
    func sleepSettings(_ name: String) async throws -> SleepSettings
    func setSleepSettings(_ name: String, request: SleepSettingsRequest) async throws -> SleepSettings
    func serverJava(_ name: String) async throws -> JavaRuntimes
    func setServerJava(_ name: String, choice: String) async throws -> JavaUsed
    func createServer(_ request: CreateServerRequest) async throws -> Job
    func alertChannels(_ name: String) async throws -> AlertList
    func addAlertChannel(_ name: String, request: AlertCreateRequest) async throws -> AlertAdded
    func testAlerts(_ name: String, channel: String?) async throws -> AlertTested
    func removeAlertChannel(_ name: String, channel: String) async throws -> AlertRemoved
    func javaRuntimes() async throws -> JavaRuntimes
    func installJava(major: Int) async throws -> Job
    func removeJava(major: Int) async throws -> OperationResult
    func remoteStatus() async throws -> RemoteStatus
    func setRemoteAccess(enabled: Bool) async throws -> RemoteStatus
    func createPairingCode(name: String?, role: String) async throws -> PairCode
    func listDevices() async throws -> DeviceList
    func setDeviceRole(_ device: String, role: String) async throws -> OperationResult
    func revokeDevice(_ device: String) async throws -> OperationResult
    func auditLog(limit: Int) async throws -> AuditLog
    func checkUpdate() async throws -> UpdateCheck
    func applyUpdate() async throws -> Job
    func rollbackUpdate() async throws -> OperationResult
    func doctor(server: String?) async throws -> DoctorReport
    func router() async throws -> RouterStatus
    func enableRouter() async throws -> RouterStatus
    func disableRouter() async throws -> RouterStatus
    func setRouterRoute(host: String, server: String) async throws -> RouterStatus
    func removeRouterRoute(host: String) async throws -> RouterStatus
    func setRouterDefault(server: String) async throws -> RouterStatus
    func editRouterAccess(list: String, action: String, cidr: String) async throws -> RouterStatus
    func modpackInfo(source: String) async throws -> ModpackInfo
    func installModpack(_ request: ModpackInstallRequest) async throws -> Job
    func updateModpack(_ name: String) async throws -> Job
    func streamEvents() -> AsyncThrowingStream<ConsoleEvent, Error>
}

public struct McClient: McClientProtocol {
    private let transport: Transport

    public init(transport: Transport) {
        self.transport = transport
    }

    public static func local(runFolders: [String]? = nil) -> McClient? {
        guard let path = ApiLocator.socketPath(runFolders: runFolders) else { return nil }
        return McClient(transport: UnixSocketTransport(path: path))
    }

    private static func ref(_ value: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    private static func serverPath(_ name: String) -> String { "/v1/servers/" + ref(name) }

    private func call<T: Decodable>(_ method: String, _ path: String, body: (any Encodable)? = nil,
                                    decoder: JSONDecoder = Coding.decoder,
                                    reported: Bool = false,
                                    as type: T.Type? = nil) async throws -> T {
        var request = HTTPRequest(method: method, path: path)
        if let body {
            request.body = try Coding.encoder.encode(AnyEncodable(body))
            request.headers["Content-Type"] = "application/json"
        }
        let response: HTTPResponse
        do {
            response = try await transport.send(request)
        } catch let error as ApiError {
            throw error
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw ApiError.unreachable
        }
        guard (200..<300).contains(response.status) else {
            throw ApiError.parse(body: response.body, status: response.status)
        }
        if !reported, let envelope = try? JSONDecoder().decode(ErrorBody.self, from: response.body), envelope.ok == false {
            throw ApiError.parse(body: response.body, status: response.status)
        }
        do {
            return try decoder.decode(T.self, from: response.body)
        } catch {
            throw ApiError.badAnswer(response.status)
        }
    }

    public func listServers() async throws -> [ServerSnapshot] {
        try await call("GET", "/v1/servers", as: ServerList.self).servers
    }

    public func server(_ name: String) async throws -> ServerSnapshot {
        try await call("GET", Self.serverPath(name))
    }

    public func start(_ name: String) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/start")
    }

    public func stop(_ name: String, request: StopRequest? = nil) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/stop", body: request)
    }

    public func restart(_ name: String) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/restart")
    }

    public func resume(_ name: String) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/resume")
    }

    public func sendCommand(_ name: String, command: String) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/console", body: ConsoleCommand(command: command))
    }

    public func onlinePlayers(_ name: String) async throws -> PlayersOnline {
        try await call("GET", Self.serverPath(name) + "/players")
    }

    public func playerList(_ name: String, kind: String) async throws -> PlayerListing {
        try await call("GET", Self.serverPath(name) + "/lists/" + Self.ref(kind))
    }

    public func addToList(_ name: String, kind: String, subject: String, reason: String?) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/lists/" + Self.ref(kind),
                       body: PlayerListAdd(subject: subject, reason: reason))
    }

    public func removeFromList(_ name: String, kind: String, subject: String) async throws -> OperationResult {
        try await call("DELETE", Self.serverPath(name) + "/lists/" + Self.ref(kind) + "/" + Self.ref(subject))
    }

    public func kick(_ name: String, player: String, reason: String?) async throws -> OperationResult {
        try await call("POST", Self.serverPath(name) + "/kick", body: KickRequest(player: player, reason: reason))
    }

    public func job(_ id: String) async throws -> Job {
        try await call("GET", "/v1/jobs/" + Self.ref(id))
    }

    public func listBackups(_ name: String) async throws -> [BackupEntry] {
        try await call("GET", Self.serverPath(name) + "/backups", as: BackupList.self).backups
    }

    public func createBackup(_ name: String) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/backups")
    }

    public func restoreBackup(_ name: String, backup: String, confirm: Bool) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/backups/" + Self.ref(backup) + "/restore",
                       body: BackupRestoreRequest(confirm: confirm))
    }

    public func listMods(_ name: String) async throws -> [ModEntry] {
        try await call("GET", Self.serverPath(name) + "/mods", as: ModList.self).mods
    }

    public func addMod(_ name: String, reference: String, source: String?) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/mods", body: ModAddRequest(ref: reference, source: source))
    }

    public func removeMod(_ name: String, mod: String, confirmBlocks: Bool) async throws -> ModRemoved {
        try await call("DELETE", Self.serverPath(name) + "/mods/" + Self.ref(mod) + (confirmBlocks ? "?confirm_blocks=true" : ""))
    }

    public func updateMods(_ name: String, mod: String?) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/mods/update", body: ModUpdateRequest(name: mod))
    }

    public func listDatapacks(_ name: String) async throws -> DatapackList {
        try await call("GET", Self.serverPath(name) + "/datapacks")
    }

    public func setDatapackEnabled(_ name: String, pack: String, enabled: Bool, placement: String? = nil) async throws -> DatapackSet {
        let request = DatapackSetRequest(
            enabled: enabled,
            first: enabled && placement == "first" ? true : nil,
            last: enabled && placement == "last" ? true : nil,
            beforeVanilla: enabled && placement == "before_vanilla" ? true : nil)
        return try await call("PUT", Self.serverPath(name) + "/datapacks/" + Self.ref(pack), body: request)
    }

    public func listWorlds(_ name: String) async throws -> WorldList {
        try await call("GET", Self.serverPath(name) + "/worlds")
    }

    public func pregenStatus(_ name: String) async throws -> PregenProgress {
        try await call("GET", Self.serverPath(name) + "/worlds/pregen")
    }

    public func startPregen(_ name: String, radius: Int, center: String?) async throws -> Pregen {
        try await call("POST", Self.serverPath(name) + "/worlds/pregen", body: PregenRequest(radius: radius, center: center))
    }

    public func resetDimension(_ name: String, dimension: String, confirmed: Bool, includeOverworld: Bool) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/worlds/" + Self.ref(dimension) + "/reset",
                       body: WorldResetRequest(confirmed: confirmed, includeOverworld: includeOverworld ? true : nil))
    }

    public func listTasks(_ name: String) async throws -> [TaskEntry] {
        try await call("GET", Self.serverPath(name) + "/tasks", as: TaskList.self).tasks
    }

    public func createTask(_ name: String, request: TaskCreateRequest) async throws -> TaskCreated {
        try await call("POST", Self.serverPath(name) + "/tasks", body: request)
    }

    public func updateTask(_ name: String, task: Int, enabled: Bool) async throws -> TaskCreated {
        try await call("PATCH", Self.serverPath(name) + "/tasks/\(task)", body: TaskPatchRequest(enabled: enabled))
    }

    public func deleteTask(_ name: String, task: Int) async throws -> TaskCreated {
        try await call("DELETE", Self.serverPath(name) + "/tasks/\(task)")
    }

    public func runTask(_ name: String, task: Int, skipWarn: Bool) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/tasks/\(task)/run",
                       body: TaskRunRequest(skipWarn: skipWarn ? true : nil))
    }

    public func serverConfig(_ name: String) async throws -> ConfigDocument {
        try await call("GET", Self.serverPath(name) + "/config", decoder: Coding.plainDecoder)
    }

    public func setConfigValue(_ name: String, key: String, value: String) async throws -> ConfigSet {
        try await call("PUT", Self.serverPath(name) + "/config/" + Self.ref(key), body: ConfigSetRequest(value: value))
    }

    public func setMode(_ name: String, mode: String) async throws -> OperationResult {
        try await call("PUT", Self.serverPath(name) + "/mode", body: ModeRequest(mode: mode))
    }

    public func setSchedule(_ name: String, schedule: ScheduleRequest) async throws -> OperationResult {
        try await call("PUT", Self.serverPath(name) + "/schedule", body: schedule)
    }

    public func sleepSettings(_ name: String) async throws -> SleepSettings {
        try await call("GET", Self.serverPath(name) + "/sleep")
    }

    public func setSleepSettings(_ name: String, request: SleepSettingsRequest) async throws -> SleepSettings {
        try await call("PUT", Self.serverPath(name) + "/sleep", body: request)
    }

    public func serverJava(_ name: String) async throws -> JavaRuntimes {
        try await call("GET", Self.serverPath(name) + "/java")
    }

    public func setServerJava(_ name: String, choice: String) async throws -> JavaUsed {
        try await call("PUT", Self.serverPath(name) + "/java", body: JavaUseRequest(choice: choice))
    }

    public func createServer(_ request: CreateServerRequest) async throws -> Job {
        try await call("POST", "/v1/servers", body: request)
    }


    public func alertChannels(_ name: String) async throws -> AlertList {
        try await call("GET", Self.serverPath(name) + "/alerts")
    }

    public func addAlertChannel(_ name: String, request: AlertCreateRequest) async throws -> AlertAdded {
        try await call("POST", Self.serverPath(name) + "/alerts", body: request)
    }

    public func testAlerts(_ name: String, channel: String?) async throws -> AlertTested {
        try await call("POST", Self.serverPath(name) + "/alerts/test", body: AlertTestRequest(channel: channel),
                       reported: true)
    }

    public func removeAlertChannel(_ name: String, channel: String) async throws -> AlertRemoved {
        try await call("DELETE", Self.serverPath(name) + "/alerts/" + Self.ref(channel))
    }

    public func javaRuntimes() async throws -> JavaRuntimes {
        try await call("GET", "/v1/java")
    }

    public func installJava(major: Int) async throws -> Job {
        try await call("PUT", "/v1/java/\(major)")
    }

    public func removeJava(major: Int) async throws -> OperationResult {
        try await call("DELETE", "/v1/java/\(major)")
    }

    public func remoteStatus() async throws -> RemoteStatus {
        try await call("GET", "/v1/remote")
    }

    public func setRemoteAccess(enabled: Bool) async throws -> RemoteStatus {
        try await call("PUT", "/v1/remote", body: RemoteEnableRequest(enabled: enabled))
    }

    public func createPairingCode(name: String?, role: String) async throws -> PairCode {
        try await call("POST", "/v1/pair/codes", body: PairCodeRequest(name: name, role: role))
    }

    public func listDevices() async throws -> DeviceList {
        try await call("GET", "/v1/devices")
    }

    public func setDeviceRole(_ device: String, role: String) async throws -> OperationResult {
        try await call("PUT", "/v1/devices/" + Self.ref(device) + "/roles",
                       body: DeviceRolesRequest(roles: DeviceRolesDocument(defaultRole: role)))
    }

    public func revokeDevice(_ device: String) async throws -> OperationResult {
        try await call("DELETE", "/v1/devices/" + Self.ref(device))
    }

    public func auditLog(limit: Int) async throws -> AuditLog {
        try await call("GET", "/v1/audit?limit=\(limit)")
    }

    public func checkUpdate() async throws -> UpdateCheck {
        try await call("GET", "/v1/update")
    }

    public func applyUpdate() async throws -> Job {
        try await call("POST", "/v1/update", body: EmptyBody())
    }

    public func rollbackUpdate() async throws -> OperationResult {
        try await call("POST", "/v1/update/rollback")
    }

    public func doctor(server: String?) async throws -> DoctorReport {
        let path = server.map { Self.serverPath($0) + "/doctor" } ?? "/v1/doctor"
        return try await call("GET", path, reported: true)
    }

    public func router() async throws -> RouterStatus {
        try await call("GET", "/v1/router", decoder: Coding.plainDecoder)
    }

    public func enableRouter() async throws -> RouterStatus {
        try await call("POST", "/v1/router/enable", body: EmptyBody(), decoder: Coding.plainDecoder)
    }

    public func disableRouter() async throws -> RouterStatus {
        try await call("POST", "/v1/router/disable", decoder: Coding.plainDecoder)
    }

    public func setRouterRoute(host: String, server: String) async throws -> RouterStatus {
        try await call("PUT", "/v1/router/routes/" + Self.ref(host), body: RouterTargetRequest(server: server),
                       decoder: Coding.plainDecoder)
    }

    public func removeRouterRoute(host: String) async throws -> RouterStatus {
        try await call("DELETE", "/v1/router/routes/" + Self.ref(host), decoder: Coding.plainDecoder)
    }

    public func setRouterDefault(server: String) async throws -> RouterStatus {
        try await call("PUT", "/v1/router/default", body: RouterTargetRequest(server: server),
                       decoder: Coding.plainDecoder)
    }

    public func editRouterAccess(list: String, action: String, cidr: String) async throws -> RouterStatus {
        try await call("POST", "/v1/router/access", body: RouterAccessRequest(list: list, action: action, cidr: cidr),
                       decoder: Coding.plainDecoder)
    }

    public func modpackInfo(source: String) async throws -> ModpackInfo {
        try await call("GET", "/v1/modpacks/info?source=" + Self.ref(source))
    }

    public func installModpack(_ request: ModpackInstallRequest) async throws -> Job {
        try await call("POST", "/v1/modpacks", body: request)
    }

    public func updateModpack(_ name: String) async throws -> Job {
        try await call("POST", Self.serverPath(name) + "/modpack/update", body: EmptyBody())
    }

    public func streamConsole(_ name: String, tail: Int = 200) -> AsyncThrowingStream<ConsoleEvent, Error> {
        events(path: Self.serverPath(name) + "/console?tail=\(tail)")
    }

    public func streamEvents() -> AsyncThrowingStream<ConsoleEvent, Error> {
        events(path: "/v1/events")
    }

    private func events(path: String) -> AsyncThrowingStream<ConsoleEvent, Error> {
        let request = HTTPRequest(method: "GET", path: path, headers: ["Accept": "text/event-stream"])
        let chunks = transport.stream(request)
        return AsyncThrowingStream { continuation in
            let task = Task {
                var parser = SSEParser()
                do {
                    for try await chunk in chunks {
                        for event in parser.feed(chunk) { continuation.yield(event) }
                    }
                    continuation.finish()
                } catch let error as ApiError {
                    continuation.finish(throwing: error)
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: ApiError.unreachable)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

private struct AnyEncodable: Encodable {
    private let encodeValue: (Encoder) throws -> Void

    init(_ value: any Encodable) {
        encodeValue = { try value.encode(to: $0) }
    }

    func encode(to encoder: Encoder) throws { try encodeValue(encoder) }
}
