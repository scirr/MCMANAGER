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
        Runtimes = new Dictionary<string, string>(JavaRuntimesFound.Concat(InstalledJava).GroupBy(p => p.Key).ToDictionary(g => g.Key, g => g.First().Value)),
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

    public List<AlertChannel> Alerts { get; } = new();
    public AlertAddRequest? AlertRequest { get; private set; }
    public Dictionary<string, string> InstalledJava { get; } = new();
    public RemoteStatus Remote { get; set; } = new() { Ok = true, Enabled = false, Fingerprint = "AB:CD" };
    public List<DeviceEntry> Devices { get; } = new();
    public List<AuditEntry> AuditLog { get; } = new();
    public UpdateInfo Update { get; set; } = new() { Ok = true, Current = "3.0.0", Latest = "3.0.0" };
    public DoctorReport Doctor { get; set; } = new() { Ok = true };
    public RouterDocument Router { get; set; } = new() { Ok = true };
    public ModpackInfo? Pack { get; set; }
    public ModpackInstallRequest? PackInstalled { get; private set; }
    public List<ConsoleEvent> Events { get; } = new();

    public async IAsyncEnumerable<ConsoleEvent> StreamEventsAsync([EnumeratorCancellation] CancellationToken ct = default)
    {
        Record("events");
        foreach (var item in Events)
        {
            await Task.Yield();
            yield return item;
        }
    }

    public Task<AlertList> ListAlertChannelsAsync(string server, CancellationToken ct = default)
    {
        Record("alerts");
        return Task.FromResult(new AlertList { Ok = true, Channels = Alerts.ToList() });
    }

    public Task<AlertAdded> AddAlertChannelAsync(string server, AlertAddRequest request, CancellationToken ct = default)
    {
        Record($"alert-add {request.Type} {request.Events} {request.Name}".TrimEnd());
        AlertRequest = request;
        Alerts.Add(new AlertChannel { Name = request.Name ?? request.Type, Type = request.Type, Topic = request.Topic });
        return Task.FromResult(new AlertAdded { Ok = true, Channel = request.Name ?? request.Type });
    }

    public Task<AlertTested> TestAlertChannelsAsync(string server, string? channel = null, CancellationToken ct = default)
    {
        Record($"alert-test {channel}".TrimEnd());
        return Task.FromResult(new AlertTested { Ok = true });
    }

    public Task<OperationResult> RemoveAlertChannelAsync(string server, string channel, CancellationToken ct = default)
    {
        Record("alert-remove " + channel);
        Alerts.RemoveAll(a => a.Name == channel);
        return Task.FromResult(Ok("removed"));
    }

    public Task<Job> InstallJavaAsync(int major, CancellationToken ct = default)
    {
        var job = NextJob("java-install " + major);
        InstalledJava[major.ToString()] = "/java/" + major;
        return Task.FromResult(job);
    }

    public Task<OperationResult> RemoveJavaAsync(int major, CancellationToken ct = default)
    {
        Record("java-remove " + major);
        InstalledJava.Remove(major.ToString());
        return Task.FromResult(Ok("removed"));
    }

    public Task<RemoteStatus> GetRemoteStatusAsync(CancellationToken ct = default)
    {
        Record("remote");
        return Task.FromResult(Remote);
    }

    public Task<RemoteStatus> SetRemoteAccessAsync(bool enabled, CancellationToken ct = default)
    {
        Record("remote-set " + enabled);
        Remote = Remote with { Enabled = enabled };
        return Task.FromResult(Remote);
    }

    public Task<PairingCodeDocument> CreatePairingCodeAsync(string role, string? name = null, CancellationToken ct = default)
    {
        Record($"pair-code {role} {name}".TrimEnd());
        return Task.FromResult(new PairingCodeDocument { Ok = true, PairingCode = "ABCD-1234", ExpiresInS = 300, Role = role });
    }

    public Task<DeviceList> ListDevicesAsync(CancellationToken ct = default)
    {
        Record("devices");
        return Task.FromResult(new DeviceList { Ok = true, Devices = Devices.ToList() });
    }

    public Task<DeviceEntry> SetDeviceRoleAsync(string device, string role, CancellationToken ct = default)
    {
        Record($"device-role {device} {role}");
        var index = Devices.FindIndex(d => d.Id == device);
        Devices[index] = Devices[index] with { Roles = new DeviceRoles { Default = role } };
        return Task.FromResult(Devices[index]);
    }

    public Task<OperationResult> RevokeDeviceAsync(string device, CancellationToken ct = default)
    {
        Record("device-revoke " + device);
        Devices.RemoveAll(d => d.Id == device);
        return Task.FromResult(Ok("revoked"));
    }

    public Task<AuditList> ListAuditLogAsync(int limit = 50, CancellationToken ct = default)
    {
        Record("audit");
        return Task.FromResult(new AuditList { Ok = true, Entries = AuditLog.ToList() });
    }

    public Task<UpdateInfo> CheckUpdateAsync(CancellationToken ct = default)
    {
        Record("update-check");
        return Task.FromResult(Update);
    }

    public Task<Job> ApplyUpdateAsync(CancellationToken ct = default)
    {
        var job = NextJob("update-apply");
        Update = Update with { Current = Update.Latest, UpdateAvailable = false, RollbackAvailable = true };
        return Task.FromResult(job);
    }

    public Task<OperationResult> RollbackUpdateAsync(CancellationToken ct = default)
    {
        Record("update-rollback");
        Update = Update with { RollbackAvailable = false };
        return Task.FromResult(Ok("rolled_back"));
    }

    public Task<DoctorReport> GetDoctorReportAsync(CancellationToken ct = default)
    {
        Record("doctor");
        return Task.FromResult(Doctor);
    }

    public Task<RouterDocument> GetRouterAsync(CancellationToken ct = default)
    {
        Record("router");
        return Task.FromResult(Router);
    }

    private Task<RouterDocument> ChangeRouter(string call, Func<RouterConfig, RouterConfig> change)
    {
        Record(call);
        Router = Router with { Config = change(Router.Config) };
        return Task.FromResult(Router);
    }

    public Task<RouterDocument> SetRouterEnabledAsync(bool enabled, CancellationToken ct = default)
        => ChangeRouter("router-enabled " + enabled, c => c with { Enabled = enabled });

    public Task<RouterDocument> SetRouterRouteAsync(string host, string server, CancellationToken ct = default)
        => ChangeRouter($"router-route {host} {server}", c => c with { Routes = new Dictionary<string, string>(c.Routes) { [host] = server } });

    public Task<RouterDocument> RemoveRouterRouteAsync(string host, CancellationToken ct = default)
        => ChangeRouter("router-route-remove " + host, c => c with { Routes = c.Routes.Where(r => r.Key != host).ToDictionary(r => r.Key, r => r.Value) });

    public Task<RouterDocument> SetRouterDefaultAsync(string server, CancellationToken ct = default)
        => ChangeRouter("router-default " + server, c => c with { Default = server });

    public Task<RouterDocument> EditRouterAccessAsync(string list, string action, string cidr, CancellationToken ct = default)
        => ChangeRouter($"router-access {list} {action} {cidr}", c =>
        {
            var current = (list == "allow" ? c.Allow : c.Deny).Where(x => x != cidr).ToList();
            if (action == "add")
            {
                current.Add(cidr);
            }
            return list == "allow" ? c with { Allow = current } : c with { Deny = current };
        });

    public Task<ModpackInfo> GetModpackInfoAsync(string source, CancellationToken ct = default)
    {
        Record("modpack-info " + source);
        return Task.FromResult(Pack ?? new ModpackInfo { Ok = true, Title = "Pack", McVersion = "1.21.1", Loader = "neoforge" });
    }

    public Task<Job> InstallModpackAsync(ModpackInstallRequest request, CancellationToken ct = default)
    {
        PackInstalled = request;
        return Task.FromResult(NextJob($"modpack-install {request.Source} {request.Name}".TrimEnd()));
    }

    public Task<Job> UpdateModpackAsync(string server, CancellationToken ct = default)
        => Task.FromResult(NextJob("modpack-update " + server));

    public Task<IReadOnlyList<Job>> ListJobsAsync(string? state = null, CancellationToken ct = default)
        => Task.FromResult<IReadOnlyList<Job>>(new List<Job>());

    public Task<Job> GetJobAsync(string id, CancellationToken ct = default)
    {
        Record("job " + id);
        return Task.FromResult(JobStates.Dequeue());
    }
}
