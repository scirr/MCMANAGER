using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using Xunit;

namespace MCManager.Client.Tests;

public class RemoteSecurityTests
{
    private static RemoteProfile Profile(TlsServer server, string? pin = null) => new()
    {
        Name = "vps", Host = "127.0.0.1", Port = server.Port,
        Fingerprint = pin ?? server.Fingerprint, Token = "mcm_secret_token_value",
    };

    private static string OtherPin()
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=other", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        using var cert = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));
        return Fingerprint.Of(cert);
    }

    [Fact]
    public void Fingerprint_format_is_uppercase_hex_separated_by_colons()
    {
        var text = Fingerprint.Format(Encoding.ASCII.GetBytes("abc"));

        Assert.Equal("BA:78:16:BF:8F:01:CF:EA:41:41:40:DE:5D:AE:22:23:B0:03:61:A3:96:17:7A:9C:B4:10:FF:61:F2:00:15:AD", text);
        Assert.True(Fingerprint.IsValid(text));
        Assert.False(Fingerprint.IsValid(text.ToLowerInvariant()));
        Assert.False(Fingerprint.IsValid(text.Replace(':', '-')));
        Assert.False(Fingerprint.IsValid(text[..^3]));
        Assert.False(Fingerprint.IsValid(""));
        Assert.False(Fingerprint.IsValid(null));
    }

    [Fact]
    public void Accepts_only_the_pinned_certificate()
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=t", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        using var cert = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));

        Assert.True(PinnedHttpHandler.Accepts(Fingerprint.Of(cert), cert));
        Assert.False(PinnedHttpHandler.Accepts(OtherPin(), cert));
        Assert.False(PinnedHttpHandler.Accepts(null, cert));
        Assert.False(PinnedHttpHandler.Accepts("", cert));
        Assert.False(PinnedHttpHandler.Accepts(Fingerprint.Of(cert), null));
    }

    [Fact]
    public async Task Matching_fingerprint_connects_over_tls13_and_sends_the_token()
    {
        using var server = new TlsServer();
        using var client = RemoteTransport.Create(Profile(server));

        var list = await client.ListServersAsync();

        Assert.Empty(list);
        Assert.Equal(1, server.Requests);
        Assert.Equal(new[] { "Bearer mcm_secret_token_value" }, server.Authorization);
    }

    [Fact]
    public async Task Different_fingerprint_is_refused_and_nothing_is_sent()
    {
        using var server = new TlsServer();
        using var client = RemoteTransport.Create(Profile(server, OtherPin()));

        var error = await Assert.ThrowsAsync<ApiException>(() => client.ListServersAsync());

        Assert.Equal("daemon_unreachable", error.Code);
        Assert.Equal(0, server.Requests);
        Assert.Empty(server.Authorization);
    }

    [Fact]
    public async Task Missing_fingerprint_is_refused_and_no_request_is_built()
    {
        using var server = new TlsServer();

        var error = Assert.Throws<ApiException>(() => RemoteTransport.Create(Profile(server, "")));
        Assert.Equal("fingerprint_missing", error.Code);

        using var http = new HttpClient(PinnedHttpHandler.Create(null));
        await Assert.ThrowsAsync<HttpRequestException>(() => http.GetAsync($"https://127.0.0.1:{server.Port}/v1/servers"));
        Assert.Equal(0, server.Requests);
    }

    [Fact]
    public async Task Fingerprint_probe_reads_the_certificate_without_sending_a_request()
    {
        using var server = new TlsServer();

        var presented = await new PairingClient().FetchFingerprintAsync("127.0.0.1", server.Port);

        Assert.Equal(server.Fingerprint, presented);
        Assert.Equal(0, server.Requests);
    }

    [Fact]
    public void Host_and_port_parsing()
    {
        Assert.True(HostPort.TryParse(" example.org:8765 ", out var host, out var port));
        Assert.Equal(("example.org", 8765), (host, port));
        Assert.True(HostPort.TryParse("[::1]:9", out host, out port));
        Assert.Equal(("::1", 9), (host, port));
        Assert.False(HostPort.TryParse("example.org", out _, out _));
        Assert.False(HostPort.TryParse("example.org:0", out _, out _));
        Assert.False(HostPort.TryParse("example.org:70000", out _, out _));
        Assert.False(HostPort.TryParse(":8765", out _, out _));
    }
}
