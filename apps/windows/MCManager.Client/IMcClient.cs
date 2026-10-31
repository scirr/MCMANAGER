namespace MCManager.Client;

public interface IMcClient
{
    Task<IReadOnlyList<ServerSnapshot>> ListServersAsync(CancellationToken ct = default);

    Task<ServerSnapshot> GetServerAsync(string server, CancellationToken ct = default);

    Task<OperationResult> StartServerAsync(string server, CancellationToken ct = default);

    Task<OperationResult> StopServerAsync(string server, StopRequest? request = null, CancellationToken ct = default);

    Task<Job> RestartServerAsync(string server, CancellationToken ct = default);

    Task<OperationResult> ResumeServerAsync(string server, CancellationToken ct = default);

    Task<OperationResult> SendConsoleCommandAsync(string server, string command, CancellationToken ct = default);

    IAsyncEnumerable<ConsoleEvent> StreamConsoleAsync(string server, int tail = 200, CancellationToken ct = default);

    Task<PlayersOnline> GetOnlinePlayersAsync(string server, CancellationToken ct = default);

    Task<PlayerListing> GetPlayerListAsync(string server, string kind, CancellationToken ct = default);

    Task<OperationResult> AddPlayerListEntryAsync(string server, string kind, string subject, string? reason = null, CancellationToken ct = default);

    Task<OperationResult> RemovePlayerListEntryAsync(string server, string kind, string subject, CancellationToken ct = default);

    Task<OperationResult> KickPlayerAsync(string server, string player, string? reason = null, CancellationToken ct = default);

    Task<IReadOnlyList<BackupEntry>> ListBackupsAsync(string server, CancellationToken ct = default);

    Task<Job> CreateBackupAsync(string server, CancellationToken ct = default);

    Task<Job> RestoreBackupAsync(string server, string backup, bool confirm, CancellationToken ct = default);

    Task<IReadOnlyList<Job>> ListJobsAsync(string? state = null, CancellationToken ct = default);

    Task<Job> GetJobAsync(string id, CancellationToken ct = default);

    Task<IReadOnlyList<ModEntry>> ListModsAsync(string server, CancellationToken ct = default);

    Task<Job> AddModAsync(string server, string reference, string? source = null, CancellationToken ct = default);

    Task<ModRemoved> RemoveModAsync(string server, string mod, bool confirmBlocks = false, CancellationToken ct = default);

    Task<Job> UpdateModsAsync(string server, string? name = null, CancellationToken ct = default);

    Task<DatapackList> ListDatapacksAsync(string server, CancellationToken ct = default);

    Task<DatapackSet> SetDatapackEnabledAsync(string server, string pack, bool enabled, string? placement = null, CancellationToken ct = default);

    Task<WorldList> ListWorldsAsync(string server, CancellationToken ct = default);

    Task<PregenProgress> GetPregenStatusAsync(string server, CancellationToken ct = default);

    Task<Pregen> StartPregenAsync(string server, int radius, string? center = null, CancellationToken ct = default);

    Task<Job> ResetDimensionAsync(string server, string dimension, bool confirmed, bool includeOverworld, CancellationToken ct = default);

    Task<IReadOnlyList<TaskEntry>> ListTasksAsync(string server, CancellationToken ct = default);

    Task<TaskCreated> CreateTaskAsync(string server, TaskCreateRequest request, CancellationToken ct = default);

    Task<TaskCreated> UpdateTaskAsync(string server, int task, bool enabled, CancellationToken ct = default);

    Task<TaskCreated> DeleteTaskAsync(string server, int task, CancellationToken ct = default);

    Task<Job> RunTaskAsync(string server, int task, bool skipWarn = false, CancellationToken ct = default);

    Task<ConfigDocument> GetServerConfigAsync(string server, CancellationToken ct = default);

    Task<ConfigSet> SetConfigValueAsync(string server, string key, string value, CancellationToken ct = default);

    Task<OperationResult> SetServerModeAsync(string server, string mode, CancellationToken ct = default);

    Task<OperationResult> SetServerScheduleAsync(string server, ScheduleRequest schedule, CancellationToken ct = default);

    Task<SleepSettings> GetSleepSettingsAsync(string server, CancellationToken ct = default);

    Task<SleepSettings> SetSleepSettingsAsync(string server, SleepSettingsRequest request, CancellationToken ct = default);

    Task<JavaRuntimes> ListServerJavaAsync(string server, CancellationToken ct = default);

    Task<JavaUsed> SetServerJavaAsync(string server, string choice, CancellationToken ct = default);

    Task<JavaRuntimes> ListJavaAsync(CancellationToken ct = default);

    Task<Job> CreateServerAsync(CreateServerRequest request, CancellationToken ct = default);

    IAsyncEnumerable<ConsoleEvent> StreamEventsAsync(CancellationToken ct = default);

    Task<AlertList> ListAlertChannelsAsync(string server, CancellationToken ct = default);

    Task<AlertAdded> AddAlertChannelAsync(string server, AlertAddRequest request, CancellationToken ct = default);

    Task<AlertTested> TestAlertChannelsAsync(string server, string? channel = null, CancellationToken ct = default);

    Task<OperationResult> RemoveAlertChannelAsync(string server, string channel, CancellationToken ct = default);

    Task<Job> InstallJavaAsync(int major, CancellationToken ct = default);

    Task<OperationResult> RemoveJavaAsync(int major, CancellationToken ct = default);

    Task<RemoteStatus> GetRemoteStatusAsync(CancellationToken ct = default);

    Task<RemoteStatus> SetRemoteAccessAsync(bool enabled, CancellationToken ct = default);

    Task<PairingCodeDocument> CreatePairingCodeAsync(string role, string? name = null, CancellationToken ct = default);

    Task<DeviceList> ListDevicesAsync(CancellationToken ct = default);

    Task<DeviceEntry> SetDeviceRoleAsync(string device, string role, CancellationToken ct = default);

    Task<OperationResult> RevokeDeviceAsync(string device, CancellationToken ct = default);

    Task<AuditList> ListAuditLogAsync(int limit = 50, CancellationToken ct = default);

    Task<UpdateInfo> CheckUpdateAsync(CancellationToken ct = default);

    Task<Job> ApplyUpdateAsync(CancellationToken ct = default);

    Task<OperationResult> RollbackUpdateAsync(CancellationToken ct = default);

    Task<DoctorReport> GetDoctorReportAsync(CancellationToken ct = default);

    Task<RouterDocument> GetRouterAsync(CancellationToken ct = default);

    Task<RouterDocument> SetRouterEnabledAsync(bool enabled, CancellationToken ct = default);

    Task<RouterDocument> SetRouterRouteAsync(string host, string server, CancellationToken ct = default);

    Task<RouterDocument> RemoveRouterRouteAsync(string host, CancellationToken ct = default);

    Task<RouterDocument> SetRouterDefaultAsync(string server, CancellationToken ct = default);

    Task<RouterDocument> EditRouterAccessAsync(string list, string action, string cidr, CancellationToken ct = default);

    Task<ModpackInfo> GetModpackInfoAsync(string source, CancellationToken ct = default);

    Task<Job> InstallModpackAsync(ModpackInstallRequest request, CancellationToken ct = default);

    Task<Job> UpdateModpackAsync(string server, CancellationToken ct = default);
}
