namespace MCManager.Client;

public sealed record AlertChannel
{
    public string Name { get; init; } = "";
    public string Type { get; init; } = "";
    public List<string> Events { get; init; } = new();
    public bool Legacy { get; init; }
    public string? Topic { get; init; }
    public string? Host { get; init; }
    public string? ChatId { get; init; }
}

public sealed record AlertList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<AlertChannel> Channels { get; init; } = new();
}

public sealed record AlertAddRequest
{
    public string Type { get; init; } = "";
    public string? Events { get; init; }
    public string? Name { get; init; }
    public string? Host { get; init; }
    public int? Port { get; init; }
    public string? User { get; init; }
    public string? Password { get; init; }
    public string? Sender { get; init; }
    public string? To { get; init; }
    public string? Token { get; init; }
    public string? ChatId { get; init; }
    public string? Server { get; init; }
    public string? Topic { get; init; }
    public string? Url { get; init; }
    public string? Secret { get; init; }
}

public sealed record AlertAdded
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Channel { get; init; } = "";
}

public sealed record AlertTestRequest
{
    public string? Channel { get; init; }
}

public sealed record AlertTested
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string? Failed { get; init; }
}

public sealed record RemoteStatus
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public bool Enabled { get; init; }
    public string? Bind { get; init; }
    public string? Fingerprint { get; init; }
}

public sealed record RemoteAccessRequest
{
    public bool Enabled { get; init; }
}

public sealed record PairingCodeRequest
{
    public string Role { get; init; } = "operator";
    public string? Name { get; init; }
}

public sealed record PairingCodeDocument
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string PairingCode { get; init; } = "";
    public int ExpiresInS { get; init; }
    public string Role { get; init; } = "";
}

public sealed record DeviceRoles
{
    public string Default { get; init; } = "viewer";
    public Dictionary<string, string>? Servers { get; init; }
}

public sealed record DeviceEntry
{
    public string Id { get; init; } = "";
    public string Name { get; init; } = "";
    public DeviceRoles Roles { get; init; } = new();
    public List<string>? Servers { get; init; }
    public string? LastSeen { get; init; }
    public string? LastIp { get; init; }
    public bool Revoked { get; init; }
}

public sealed record DeviceList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<DeviceEntry> Devices { get; init; } = new();
}

public sealed record DeviceRolesRequest
{
    public DeviceRoles Roles { get; init; } = new();
}

public sealed record AuditEntry
{
    public string At { get; init; } = "";
    public string Action { get; init; } = "";
    public string? Device { get; init; }
    public string? Server { get; init; }
    public bool Ok { get; init; }
    public string? Result { get; init; }
}

public sealed record AuditList
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<AuditEntry> Entries { get; init; } = new();
}

public sealed record UpdateInfo
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string Current { get; init; } = "";
    public string Latest { get; init; } = "";
    public bool UpdateAvailable { get; init; }
    public bool RollbackAvailable { get; init; }
}

public sealed record UpdateRequest
{
    public string? Version { get; init; }
}

public sealed record DoctorCheck
{
    public string? Server { get; init; }
    public string Name { get; init; } = "";
    public bool Ok { get; init; }
    public string? Level { get; init; }
    public string? Detail { get; init; }
    public string? Fix { get; init; }
}

public sealed record DoctorReport
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public List<DoctorCheck> Checks { get; init; } = new();
    public int Errors { get; init; }
    public int Warnings { get; init; }
}

public sealed record RouterConfig
{
    public bool Enabled { get; init; }
    public int Port { get; init; }
    public string? Default { get; init; }
    public Dictionary<string, string> Routes { get; init; } = new();
    public List<string> Allow { get; init; } = new();
    public List<string> Deny { get; init; } = new();
}

public sealed record RouterDocument
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public RouterConfig Config { get; init; } = new();
    public List<string> PendingRestart { get; init; } = new();
}

public sealed record RouterServerRequest
{
    public string Server { get; init; } = "";
}

public sealed record RouterAccessRequest
{
    public string List { get; init; } = "";
    public string Action { get; init; } = "";
    public string Cidr { get; init; } = "";
}

public sealed record RouterEnableRequest
{
}

public sealed record ModpackInfo
{
    public bool Ok { get; init; }
    public string Code { get; init; } = "";
    public string? Title { get; init; }
    public string? Version { get; init; }
    public string McVersion { get; init; } = "";
    public string Loader { get; init; } = "";
}

public sealed record ModpackInstallRequest
{
    public string Source { get; init; } = "";
    public bool AcceptEula { get; init; }
    public string? Name { get; init; }
    public string? Ram { get; init; }
    public int? Port { get; init; }
    public int? RconPort { get; init; }
}

public sealed record ModpackUpdateRequest
{
}
