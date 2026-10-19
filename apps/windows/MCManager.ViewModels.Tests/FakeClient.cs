using System.Runtime.CompilerServices;
using MCManager.Client;

namespace MCManager.ViewModels.Tests;

internal sealed class FakeClient : IMcClient
{
    public List<ServerSnapshot> Servers { get; } = new();
    public Dictionary<string, PlayersOnline> Online { get; } = new();
    public Dictionary<string, List<PlayerListEntry>> Lists { get; } = new();
    public List<ConsoleEvent> Stream { get; } = new();
    public List<string> Calls { get; } = new();
    public ApiException? Failure { get; set; }
    public ApiException? PlayersFailure { get; set; }
    public Queue<Job> JobStates { get; } = new();
    public string State { get; set; } = "running";

    private void Record(string call)
    {
        Calls.Add(call);
        if (Failure is not null)
        {
            throw Failure;
        }
    }

    private static OperationResult Ok(string code) => new() { Ok = true, Code = code };

    public Task<IReadOnlyList<ServerSnapshot>> ListServersAsync(CancellationToken ct = default)
    {
        Record("list");
        return Task.FromResult<IReadOnlyList<ServerSnapshot>>(Servers.ToList());
    }

    public Task<ServerSnapshot> GetServerAsync(string server, CancellationToken ct = default)
    {
        Record("get " + server);
        return Task.FromResult(new ServerSnapshot { Name = server, State = State, Version = "1.21.1", Loader = "Fabric", RssKb = 2097152 });
    }

    public Task<OperationResult> StartServerAsync(string server, CancellationToken ct = default)
    {
        Record("start " + server);
        State = "running";
        return Task.FromResult(Ok("started"));
    }

    public Task<OperationResult> StopServerAsync(string server, StopRequest? request = null, CancellationToken ct = default)
    {
        Record("stop " + server);
        State = "stopped";
        return Task.FromResult(Ok("stopped"));
    }

    public Task<Job> RestartServerAsync(string server, CancellationToken ct = default)
    {
        Record("restart " + server);
        return Task.FromResult(new Job { Id = "j1", State = "running" });
    }

    public Task<OperationResult> ResumeServerAsync(string server, CancellationToken ct = default)
    {
        Record("resume " + server);
        State = "running";
        return Task.FromResult(Ok("resumed"));
    }

    public Task<OperationResult> SendConsoleCommandAsync(string server, string command, CancellationToken ct = default)
    {
        Record("console " + command);
        return Task.FromResult(new OperationResult { Ok = true, Code = "console_reply", Output = "line1\nline2" });
    }

    public async IAsyncEnumerable<ConsoleEvent> StreamConsoleAsync(
        string server, int tail = 200, [EnumeratorCancellation] CancellationToken ct = default)
    {
        Record("stream " + server);
        foreach (var item in Stream)
        {
            await Task.Yield();
            yield return item;
        }
    }

    public Task<PlayersOnline> GetOnlinePlayersAsync(string server, CancellationToken ct = default)
    {
        Calls.Add("players " + server);
        if (PlayersFailure is not null)
        {
            throw PlayersFailure;
        }
        return Task.FromResult(Online.TryGetValue(server, out var players) ? players : new PlayersOnline { Ok = true });
    }

    public Task<PlayerListing> GetPlayerListAsync(string server, string kind, CancellationToken ct = default)
    {
        Record("list " + kind);
        var entries = Lists.TryGetValue(kind, out var found) ? found.ToList() : new List<PlayerListEntry>();
        return Task.FromResult(new PlayerListing { Ok = true, Entries = entries });
    }

    public Task<OperationResult> AddPlayerListEntryAsync(string server, string kind, string subject, string? reason = null, CancellationToken ct = default)
    {
        Record($"add {kind} {subject} {reason}".TrimEnd());
        if (!Lists.TryGetValue(kind, out var list))
        {
            Lists[kind] = list = new List<PlayerListEntry>();
        }
        list.Add(new PlayerListEntry { Name = subject });
        return Task.FromResult(Ok("added"));
    }

    public Task<OperationResult> RemovePlayerListEntryAsync(string server, string kind, string subject, CancellationToken ct = default)
    {
        Record($"remove {kind} {subject}");
        Lists[kind].RemoveAll(e => e.Subject == subject);
        return Task.FromResult(Ok("removed"));
    }

    public Task<OperationResult> KickPlayerAsync(string server, string player, string? reason = null, CancellationToken ct = default)
    {
        Record("kick " + player);
        return Task.FromResult(Ok("kicked"));
    }

    public List<BackupEntry> Backups { get; } = new();

    public Task<IReadOnlyList<BackupEntry>> ListBackupsAsync(string server, CancellationToken ct = default)
    {
        Record("backups " + server);
        return Task.FromResult<IReadOnlyList<BackupEntry>>(Backups.ToList());
    }

    public Task<Job> CreateBackupAsync(string server, CancellationToken ct = default)
    {
        Record("create-backup " + server);
        return Task.FromResult(new Job { Id = "jb", State = "running" });
    }

    public Task<Job> RestoreBackupAsync(string server, string backup, bool confirm, CancellationToken ct = default)
    {
        Record($"restore {backup} {confirm}");
        return Task.FromResult(new Job { Id = "jr", State = "running" });
    }

    public Task<IReadOnlyList<Job>> ListJobsAsync(string? state = null, CancellationToken ct = default)
        => Task.FromResult<IReadOnlyList<Job>>(new List<Job>());

    public Task<Job> GetJobAsync(string id, CancellationToken ct = default)
    {
        Record("job " + id);
        return Task.FromResult(JobStates.Dequeue());
    }
}
