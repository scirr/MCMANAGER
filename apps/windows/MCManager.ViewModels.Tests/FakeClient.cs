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
        return Task.FromResult(new ServerSnapshot { Name = server, State = State, Version = "1.21.1", Loader = "Fabric", RssKb = 2097152, Mode = Mode });
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

    public List<ModEntry> Mods { get; } = new();
    public List<DatapackEntry> Packs { get; } = new();
    public bool PacksRunning { get; set; }
    public List<WorldDimension> Dimensions { get; } = new();
    public string PregenReply { get; set; } = "";
    public ApiException? PregenFailure { get; set; }
    public List<TaskEntry> Tasks { get; } = new();
    public Dictionary<string, System.Text.Json.JsonElement> Config { get; } = new();
    public List<string> Secrets { get; } = new();
    public Dictionary<string, string> JavaRuntimesFound { get; } = new();
    public string ServerJava { get; set; } = "system";
    public string Mode { get; set; } = "schedule";
    public bool RestartNeeded { get; set; }
    public Queue<Job> StartedJobs { get; } = new();
    public CreateServerRequest? Created { get; private set; }

    private Job NextJob(string call)
    {
        Record(call);
        return StartedJobs.Count > 0 ? StartedJobs.Dequeue() : new Job { Id = "jx", State = "running" };
    }

    public Task<IReadOnlyList<ModEntry>> ListModsAsync(string server, CancellationToken ct = default)
    {
        Record("mods " + server);
        return Task.FromResult<IReadOnlyList<ModEntry>>(Mods.ToList());
    }

    public Task<Job> AddModAsync(string server, string reference, string? source = null, CancellationToken ct = default)
        => Task.FromResult(NextJob($"add-mod {reference} {source}".TrimEnd()));

    public Task<ModRemoved> RemoveModAsync(string server, string mod, bool confirmBlocks = false, CancellationToken ct = default)
    {
        Record($"remove-mod {mod} {confirmBlocks}");
        Mods.RemoveAll(m => m.File == mod);
        return Task.FromResult(new ModRemoved { Ok = true, Code = "removed", File = mod, RestartRequired = true });
    }

    public Task<Job> UpdateModsAsync(string server, string? name = null, CancellationToken ct = default)
        => Task.FromResult(NextJob("update-mods"));

    public Task<DatapackList> ListDatapacksAsync(string server, CancellationToken ct = default)
    {
        Record("datapacks");
        return Task.FromResult(new DatapackList { Ok = true, Running = PacksRunning, Packs = Packs.ToList() });
    }

    public Task<DatapackSet> SetDatapackEnabledAsync(string server, string pack, bool enabled, string? placement = null, CancellationToken ct = default)
    {
        Record($"datapack {pack} {enabled}" + (placement is null ? "" : " " + placement));
        var index = Packs.FindIndex(p => p.File == pack);
        if (index >= 0)
        {
            Packs[index] = Packs[index] with { Enabled = enabled };
        }
        return Task.FromResult(new DatapackSet { Ok = true, Pack = pack, RestartRequired = RestartNeeded });
    }

    public Task<WorldList> ListWorldsAsync(string server, CancellationToken ct = default)
    {
        Record("worlds");
        return Task.FromResult(new WorldList { Ok = true, Level = "world", SizeBytes = Dimensions.Sum(d => d.SizeBytes), Dimensions = Dimensions.ToList() });
    }

    public Task<PregenProgress> GetPregenStatusAsync(string server, CancellationToken ct = default)
    {
        Calls.Add("pregen-status");
        if (PregenFailure is not null)
        {
            throw PregenFailure;
        }
        return Task.FromResult(new PregenProgress { Ok = true, Progress = PregenReply });
    }

    public Task<Pregen> StartPregenAsync(string server, int radius, string? center = null, CancellationToken ct = default)
    {
        Record($"pregen {radius} {center}".TrimEnd());
        return Task.FromResult(new Pregen { Ok = true, Radius = radius, Progress = "Task running." });
    }

    public Task<Job> ResetDimensionAsync(string server, string dimension, bool confirmed, bool includeOverworld, CancellationToken ct = default)
        => Task.FromResult(NextJob($"reset {dimension} {confirmed} {includeOverworld}"));

    public Task<IReadOnlyList<TaskEntry>> ListTasksAsync(string server, CancellationToken ct = default)
    {
        Record("tasks");
        return Task.FromResult<IReadOnlyList<TaskEntry>>(Tasks.ToList());
    }

    public Task<TaskCreated> CreateTaskAsync(string server, TaskCreateRequest request, CancellationToken ct = default)
    {
        Record($"task-create {request.Action} {request.Cron} {request.Name} {request.Command} {request.Warn}");
        var task = new TaskEntry { Id = Tasks.Count + 1, Name = request.Name ?? "t", Cron = request.Cron, Action = request.Action, Enabled = true };
        Tasks.Add(task);
        return Task.FromResult(new TaskCreated { Ok = true, Task = task });
    }

    public Task<TaskCreated> UpdateTaskAsync(string server, int task, bool enabled, CancellationToken ct = default)
    {
        Record($"task-update {task} {enabled}");
        var index = Tasks.FindIndex(t => t.Id == task);
        Tasks[index] = Tasks[index] with { Enabled = enabled };
        return Task.FromResult(new TaskCreated { Ok = true, Task = Tasks[index] });
    }

    public Task<TaskCreated> DeleteTaskAsync(string server, int task, CancellationToken ct = default)
    {
        Record($"task-delete {task}");
        Tasks.RemoveAll(t => t.Id == task);
        return Task.FromResult(new TaskCreated { Ok = true });
    }

    public Task<Job> RunTaskAsync(string server, int task, bool skipWarn = false, CancellationToken ct = default)
        => Task.FromResult(NextJob($"task-run {task}"));

    public Task<ConfigDocument> GetServerConfigAsync(string server, CancellationToken ct = default)
    {
        Record("config");
        return Task.FromResult(new ConfigDocument { Ok = true, Config = new Dictionary<string, System.Text.Json.JsonElement>(Config), SecretsSet = Secrets.ToList() });
    }

    public Task<ConfigSet> SetConfigValueAsync(string server, string key, string value, CancellationToken ct = default)
    {
        Record($"config-set {key}={value}");
        return Task.FromResult(new ConfigSet { Ok = true, Key = key, RestartRequired = RestartNeeded });
    }

    public Task<OperationResult> SetServerModeAsync(string server, string mode, CancellationToken ct = default)
    {
        Record("mode " + mode);
        Mode = mode;
        return Task.FromResult(Ok("mode_set"));
    }

    public Task<OperationResult> SetServerScheduleAsync(string server, ScheduleRequest schedule, CancellationToken ct = default)
    {
        Record($"schedule {schedule.OpenHour}:{schedule.OpenMinute}-{schedule.CloseHour}:{schedule.CloseMinute}");
        return Task.FromResult(Ok("schedule_updated"));
    }

    public SleepSettings Sleep { get; set; } = new() { Ok = true, Enabled = false, AfterS = 7200, JoinMode = "kick" };

    public Task<SleepSettings> GetSleepSettingsAsync(string server, CancellationToken ct = default)
    {
        Record("sleep-get");
        return Task.FromResult(Sleep);
    }

    public Task<SleepSettings> SetSleepSettingsAsync(string server, SleepSettingsRequest request, CancellationToken ct = default)
    {
        Record($"sleep-set {request.Enabled} {request.AfterS} {request.JoinMode} {request.Freeze}");
        Sleep = Sleep with
        {
            Enabled = request.Enabled ?? Sleep.Enabled,
            AfterS = request.AfterS ?? Sleep.AfterS,
            JoinMode = request.JoinMode ?? Sleep.JoinMode,
            Freeze = request.Freeze ?? Sleep.Freeze,
        };
        return Task.FromResult(Sleep);
    }

    public Task<JavaRuntimes> ListServerJavaAsync(string server, CancellationToken ct = default)
    {
        Record("java-list");
        return Task.FromResult(JavaState(server));
    }

    private JavaRuntimes JavaState(string server) => new()
    {
        Ok = true,
        Runtimes = new Dictionary<string, string>(JavaRuntimesFound),
        Servers = new List<JavaServerChoice>
        {
            new() { Server = server, Java = System.Text.Json.JsonDocument.Parse("\"" + ServerJava + "\"").RootElement },
        },
    };

    public Task<JavaUsed> SetServerJavaAsync(string server, string choice, CancellationToken ct = default)
    {
        Record("java-set " + choice);
        ServerJava = choice;
        return Task.FromResult(new JavaUsed { Ok = true, RestartRequired = RestartNeeded });
    }

    public Task<JavaRuntimes> ListJavaAsync(CancellationToken ct = default)
    {
        Record("java-all");
        return Task.FromResult(JavaState(""));
    }

    public Task<Job> CreateServerAsync(CreateServerRequest request, CancellationToken ct = default)
    {
        Created = request;
        return Task.FromResult(NextJob("create-server " + request.Name));
    }

    public Task<IReadOnlyList<Job>> ListJobsAsync(string? state = null, CancellationToken ct = default)
        => Task.FromResult<IReadOnlyList<Job>>(new List<Job>());

    public Task<Job> GetJobAsync(string id, CancellationToken ct = default)
    {
        Record("job " + id);
        return Task.FromResult(JobStates.Dequeue());
    }
}
