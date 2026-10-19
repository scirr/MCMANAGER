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
