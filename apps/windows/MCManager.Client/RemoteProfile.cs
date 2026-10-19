namespace MCManager.Client;

public sealed record RemoteProfile
{
    public string Name { get; init; } = "";
    public string Host { get; init; } = "";
    public int Port { get; init; }
    public string Fingerprint { get; init; } = "";
    public string Token { get; init; } = "";
    public string DeviceId { get; init; } = "";

    public RemoteSummary Summary() => new(Name, Host, Port, Fingerprint);

    public override string ToString() => $"{Name} ({Host}:{Port})";
}

public sealed record RemoteSummary(string Name, string Host, int Port, string Fingerprint);

public static class HostPort
{
    public static bool TryParse(string? text, out string host, out int port)
    {
        host = "";
        port = 0;
        var value = (text ?? "").Trim();
        var cut = value.LastIndexOf(':');
        if (cut <= 0 || !int.TryParse(value.AsSpan(cut + 1), out port) || port is <= 0 or > 65535)
        {
            port = 0;
            return false;
        }
        host = value[..cut].Trim('[', ']');
        if (host.Length == 0 || host.Any(char.IsWhiteSpace))
        {
            host = "";
            port = 0;
            return false;
        }
        return true;
    }
}
