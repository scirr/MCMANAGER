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

    Task<IReadOnlyList<Job>> ListJobsAsync(string? state = null, CancellationToken ct = default);

    Task<Job> GetJobAsync(string id, CancellationToken ct = default);
}
