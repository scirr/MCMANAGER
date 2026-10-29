using System.Text.Json;

namespace MCManager.Client;

public sealed record ServerSnapshotError
{
    public string? Code { get; init; }
}

public sealed record ServerSnapshot
{
    public bool Ok { get; init; } = true;
    public string Code { get; init; } = "";
    public int? Id { get; init; }
    public string Name { get; init; } = "";
    public string Server { get; init; } = "";
    public bool Active { get; init; }
    public string? State { get; init; }
    public string? Mode { get; init; }
    public string? Loader { get; init; }
    public string? Version { get; init; }
    public int? Port { get; init; }
    public int? Pid { get; init; }
    public long? RssKb { get; init; }
    public long? UptimeS { get; init; }
    public bool Frozen { get; init; }
    public bool Maintenance { get; init; }
    public string? StopReason { get; init; }
    public ServerSnapshotError? Error { get; init; }
}

public sealed record ServerList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string? Active { get; init; }
    public List<ServerSnapshot> Servers { get; init; } = new();
}

public sealed record PlayersOnline
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Server { get; init; } = "";
    public string? State { get; init; }
    public int Online { get; init; }
    public int? Max { get; init; }
    public List<string> Players { get; init; } = new();
}

public sealed record PlayerListEntry
{
    public string? Name { get; init; }
    public string? Uuid { get; init; }
    public string? Ip { get; init; }
    public string? Reason { get; init; }
    public int? Level { get; init; }
    public string? Expires { get; init; }

    public string Subject => Name ?? Ip ?? "";
}

public sealed record PlayerListing
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Server { get; init; } = "";
    public bool? Enabled { get; init; }
    public List<PlayerListEntry> Entries { get; init; } = new();
}

public sealed record OperationResult
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string? Message { get; init; }
    public string? Server { get; init; }
    public string? Subject { get; init; }
    public bool? Changed { get; init; }
    public string? Via { get; init; }
    public string? Output { get; init; }
    public string? Mode { get; init; }
}

public sealed record JobResult
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string? Message { get; init; }
}

public sealed record Job
{
    public string Id { get; init; } = "";
    public string Kind { get; init; } = "";
    public string State { get; init; } = "";
    public string? Code { get; init; }
    public int? Progress { get; init; }
    public string? Server { get; init; }
    public JobResult? Result { get; init; }

    public bool IsFinished => State is "succeeded" or "failed" or "cancelled";
}

public sealed record BackupEntry
{
    public string Id { get; init; } = "";
    public string File { get; init; } = "";
    public string Type { get; init; } = "";
    public string Created { get; init; } = "";
    public long CreatedTs { get; init; }
    public long Size { get; init; }
    public bool Encrypted { get; init; }
}

public sealed record BackupList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<BackupEntry> Backups { get; init; } = new();
}

public sealed record BackupRestoreRequest
{
    public bool Confirm { get; init; }
}

public sealed record JobList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<Job> Jobs { get; init; } = new();
}

public sealed record StopRequest
{
    public bool? Force { get; init; }
    public bool? Quiet { get; init; }
    public string? Reason { get; init; }
}

public sealed record ConsoleCommand
{
    public string Command { get; init; } = "";
}

public sealed record PlayerListAdd
{
    public string Subject { get; init; } = "";
    public string? Reason { get; init; }
}

public sealed record KickRequest
{
    public string Player { get; init; } = "";
    public string? Reason { get; init; }
}

public sealed record ModEntry
{
    public string File { get; init; } = "";
    public string? Id { get; init; }
    public string? Name { get; init; }
    public string? Version { get; init; }
    public string? Loader { get; init; }
    public string? Source { get; init; }
    public string? Project { get; init; }
    public string? TrackedVersion { get; init; }
    public bool Server { get; init; }
    public bool Modpack { get; init; }
    public bool AddsBlocks { get; init; }
}

public sealed record ModList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<ModEntry> Mods { get; init; } = new();
}

public sealed record ModAddRequest
{
    public string Ref { get; init; } = "";
    public string? Source { get; init; }
    public bool? ServerOnly { get; init; }
}

public sealed record ModUpdateRequest
{
    public string? Name { get; init; }
}

public sealed record ModRemoved
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string File { get; init; } = "";
    public bool RestartRequired { get; init; }
}

public sealed record DatapackEntry
{
    public string Id { get; init; } = "";
    public string File { get; init; } = "";
    public bool? Enabled { get; init; }
    public int? Order { get; init; }
    public bool Worldgen { get; init; }
    public string? Problem { get; init; }
}

public sealed record DatapackList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public bool Running { get; init; }
    public List<DatapackEntry> Packs { get; init; } = new();
}

public sealed record DatapackSetRequest
{
    public bool Enabled { get; init; }
    public bool? First { get; init; }
    public bool? Last { get; init; }
    public bool? BeforeVanilla { get; init; }
}

public sealed record DatapackSet
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Pack { get; init; } = "";
    public bool RestartRequired { get; init; }
}

public sealed record WorldDimension
{
    public string Id { get; init; } = "";
    public long SizeBytes { get; init; }
}

public sealed record WorldList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Level { get; init; } = "";
    public long SizeBytes { get; init; }
    public List<WorldDimension> Dimensions { get; init; } = new();
}

public sealed record PregenProgress
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Progress { get; init; } = "";
}

public sealed record PregenRequest
{
    public int Radius { get; init; }
    public string? Center { get; init; }
}

public sealed record Pregen
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public int Radius { get; init; }
    public string? Progress { get; init; }
}

public sealed record WorldResetRequest
{
    public bool Confirmed { get; init; }
    public bool? IncludeOverworld { get; init; }
}

public sealed record TaskLastResult
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
}

public sealed record TaskEntry
{
    public int Id { get; init; }
    public string Name { get; init; } = "";
    public string Cron { get; init; } = "";
    public string Action { get; init; } = "";
    public string? Command { get; init; }
    public bool Enabled { get; init; }
    public List<int> Warn { get; init; } = new();
    public string? LastRun { get; init; }
    public string? NextRun { get; init; }
    public TaskLastResult? LastResult { get; init; }
}

public sealed record TaskList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<TaskEntry> Tasks { get; init; } = new();
}

public sealed record TaskCreated
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public TaskEntry? Task { get; init; }
}

public sealed record TaskCreateRequest
{
    public string Cron { get; init; } = "";
    public string Action { get; init; } = "";
    public string? Name { get; init; }
    public string? Command { get; init; }
    public string? Warn { get; init; }
}

public sealed record TaskPatchRequest
{
    public bool Enabled { get; init; }
}

public sealed record TaskRunRequest
{
    public bool? SkipWarn { get; init; }
}

public sealed record ConfigDocument
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public Dictionary<string, JsonElement> Config { get; init; } = new();
    public List<string> SecretsSet { get; init; } = new();
}

public sealed record ConfigSetRequest
{
    public string Value { get; init; } = "";
}

public sealed record ConfigSet
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Key { get; init; } = "";
    public bool RestartRequired { get; init; }
}

public sealed record ModeRequest
{
    public string Mode { get; init; } = "";
}

public sealed record ScheduleRequest
{
    public int OpenHour { get; init; }
    public int OpenMinute { get; init; }
    public int CloseHour { get; init; }
    public int CloseMinute { get; init; }
}

public sealed record SleepSettings
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public bool Enabled { get; init; }
    public int AfterS { get; init; }
    public string JoinMode { get; init; } = "kick";
    public int HoldTimeoutS { get; init; }
    public bool Freeze { get; init; }
    public bool FreezeSupported { get; init; } = true;
    public List<string> Allow { get; init; } = new();
    public List<string> Notes { get; init; } = new();
}

public sealed record SleepSettingsRequest
{
    public bool? Enabled { get; init; }
    public int? AfterS { get; init; }
    public string? JoinMode { get; init; }
    public bool? Freeze { get; init; }
}

public sealed record JavaServerChoice
{
    public string Server { get; init; } = "";
    public JsonElement Java { get; init; }
    public string? Minecraft { get; init; }

    public string JavaText => Java.ValueKind switch
    {
        JsonValueKind.String => Java.GetString() ?? "",
        JsonValueKind.Number => Java.GetRawText(),
        _ => "",
    };
}

public sealed record JavaRuntimes
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public Dictionary<string, string> Runtimes { get; init; } = new();
    public List<JavaServerChoice> Servers { get; init; } = new();
}

public sealed record JavaUseRequest
{
    public string Choice { get; init; } = "";
}

public sealed record JavaUsed
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public bool RestartRequired { get; init; }
}

public sealed record CreateServerRequest
{
    public string Name { get; init; } = "";
    public string Loader { get; init; } = "";
    public bool AcceptEula { get; init; }
    public string? Version { get; init; }
    public string? Ram { get; init; }
    public int? Port { get; init; }
    public int? RconPort { get; init; }
}

public sealed record ErrorBody
{
    public string? Code { get; init; }
    public string? Message { get; init; }
}

public sealed record TokenFile
{
    public int Port { get; init; }
    public string Token { get; init; } = "";
}

public sealed record ConsoleEvent(string? Id, string Name, string Data);
