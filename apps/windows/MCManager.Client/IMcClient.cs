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

    Task<DatapackSet> SetDatapackEnabledAsync(string server, string pack, bool enabled, CancellationToken ct = default);

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

    Task<JavaRuntimes> ListServerJavaAsync(string server, CancellationToken ct = default);

    Task<JavaUsed> SetServerJavaAsync(string server, string choice, CancellationToken ct = default);

    Task<JavaRuntimes> ListJavaAsync(CancellationToken ct = default);

    Task<Job> CreateServerAsync(CreateServerRequest request, CancellationToken ct = default);
}
