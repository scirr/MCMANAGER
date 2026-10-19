using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;

namespace MCManager.Client;

public interface IPairingClient
{
    Task<string> FetchFingerprintAsync(string host, int port, CancellationToken ct = default);

    Task<RemoteProfile> PairAsync(string host, int port, string fingerprint, string code, string name, CancellationToken ct = default);
}

public sealed class PairingClient : IPairingClient
{
    private readonly Func<string, HttpMessageHandler> _handlerFactory;

    public PairingClient(Func<string, HttpMessageHandler>? handlerFactory = null)
    {
        _handlerFactory = handlerFactory ?? (pin => PinnedHttpHandler.Create(pin));
    }

    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(20);

    public async Task<string> FetchFingerprintAsync(string host, int port, CancellationToken ct = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(Timeout);
        string? presented = null;
        try
        {
            using var tcp = new TcpClient();
            await tcp.ConnectAsync(host, port, timeout.Token).ConfigureAwait(false);
            using var tls = new SslStream(tcp.GetStream(), false, (_, cert, _, _) =>
            {
                presented = cert is null ? null : Fingerprint.Of(cert);
                return false;
            });
            var options = new SslClientAuthenticationOptions
            {
                TargetHost = host,
                EnabledSslProtocols = SslProtocols.Tls13,
            };
            try
            {
                await tls.AuthenticateAsClientAsync(options, timeout.Token).ConfigureAwait(false);
            }
            catch (AuthenticationException) when (presented is not null)
            {
            }
        }
        catch (Exception ex) when (ex is IOException or SocketException or AuthenticationException)
        {
            throw new ApiException("remote_unreachable", ex.Message, 0);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new ApiException("remote_unreachable", "", 0);
        }
        return presented ?? throw new ApiException("remote_unreachable", "", 0);
    }

    public async Task<RemoteProfile> PairAsync(string host, int port, string fingerprint, string code, string name, CancellationToken ct = default)
    {
        if (!Fingerprint.IsValid(fingerprint))
        {
            throw new ApiException("fingerprint_missing", "", 0);
        }
        using var http = new HttpClient(_handlerFactory(fingerprint), true)
        {
            BaseAddress = RemoteTransport.BaseAddress(host, port),
            Timeout = System.Threading.Timeout.InfiniteTimeSpan,
        };
        var body = JsonSerializer.Serialize(new PairRequest { Code = code, Name = name }, McJson.Default.PairRequest);
        using var request = new HttpRequestMessage(HttpMethod.Post, "/v1/pair")
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(Timeout);
        string text;
        int status;
        try
        {
            using var response = await http.SendAsync(request, timeout.Token).ConfigureAwait(false);
            status = (int)response.StatusCode;
            text = await response.Content.ReadAsStringAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            throw new ApiException(ex.InnerException is AuthenticationException ? "fingerprint_mismatch" : "remote_unreachable", ex.Message, 0);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new ApiException("daemon_timeout", "", 0);
        }

        if (status != 201)
        {
            throw McClient.ParseError(text, status);
        }
        PairResult? result;
        try
        {
            result = JsonSerializer.Deserialize(text, McJson.Default.PairResult);
        }
        catch (JsonException)
        {
            throw new ApiException("bad_answer", "", status);
        }
        if (result is null || !result.Ok || string.IsNullOrEmpty(result.Token))
        {
            throw new ApiException("bad_answer", "", status);
        }
        if (!string.IsNullOrEmpty(result.Fingerprint) && !Fingerprint.Equal(result.Fingerprint, fingerprint))
        {
            throw new ApiException("fingerprint_mismatch", "", status);
        }
        return new RemoteProfile
        {
            Name = name,
            Host = host,
            Port = port,
            Fingerprint = fingerprint.ToUpperInvariant(),
            Token = result.Token,
            DeviceId = result.DeviceId ?? "",
        };
    }
}

public sealed record PairRequest
{
    public string Code { get; init; } = "";
    public string Name { get; init; } = "";
}

public sealed record PairResult
{
    public bool Ok { get; init; }
    public string? DeviceId { get; init; }
    public string? Token { get; init; }
    public string? Fingerprint { get; init; }
}
