using MCManager.Client;

namespace MCManager.ViewModels.Tests;

internal sealed class FakePairing : IPairingClient
{
    public const string Pin = "9F:2A:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:C1";

    public ApiException? Failure { get; set; }
    public List<string> Calls { get; } = new();

    public Task<string> FetchFingerprintAsync(string host, int port, CancellationToken ct = default)
    {
        Calls.Add($"fetch {host}:{port}");
        return Task.FromResult(Pin);
    }

    public Task<RemoteProfile> PairAsync(string host, int port, string fingerprint, string code, string name, CancellationToken ct = default)
    {
        Calls.Add($"pair {fingerprint} {code} {name}");
        if (Failure is not null)
        {
            throw Failure;
        }
        return Task.FromResult(new RemoteProfile { Name = name, Host = host, Port = port, Fingerprint = fingerprint, Token = "mcm_tok", DeviceId = "d" });
    }
}

internal sealed class TestProtector : IProfileProtector
{
    public byte[] Protect(byte[] plain) => plain.Select(b => (byte)(b ^ 0x5A)).ToArray();

    public byte[] Unprotect(byte[] protectedData) => Protect(protectedData);
}
