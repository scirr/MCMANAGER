using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace MCManager.Client.Tests;

internal sealed class TlsServer : IDisposable
{
    private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
    private readonly X509Certificate2 _certificate;
    private readonly CancellationTokenSource _stop = new();
    private int _requests;

    public TlsServer()
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=mcmanager-test", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        using var created = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(30));
        _certificate = new X509Certificate2(created.Export(X509ContentType.Pfx));
        _listener.Start();
        Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
        _ = Task.Run(LoopAsync);
    }

    public int Port { get; }

    public int Requests => Volatile.Read(ref _requests);

    public string Fingerprint => MCManager.Client.Fingerprint.Of(_certificate);

    public List<string> Authorization { get; } = new();

    public string Body { get; set; } = "{\"ok\":true,\"servers\":[]}";

    private async Task LoopAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            TcpClient tcp;
            try
            {
                tcp = await _listener.AcceptTcpClientAsync(_stop.Token);
            }
            catch (Exception)
            {
                return;
            }
            _ = Task.Run(() => HandleAsync(tcp));
        }
    }

    private async Task HandleAsync(TcpClient tcp)
    {
        using (tcp)
        {
            try
            {
                using var tls = new SslStream(tcp.GetStream(), false);
                await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
                {
                    ServerCertificate = _certificate,
                    EnabledSslProtocols = SslProtocols.Tls13,
                });
                var received = new StringBuilder();
                var buffer = new byte[4096];
                while (!received.ToString().Contains("\r\n\r\n"))
                {
                    var count = await tls.ReadAsync(buffer);
                    if (count == 0)
                    {
                        return;
                    }
                    received.Append(Encoding.ASCII.GetString(buffer, 0, count));
                }
                Interlocked.Increment(ref _requests);
                foreach (var line in received.ToString().Split("\r\n"))
                {
                    if (line.StartsWith("authorization:", StringComparison.OrdinalIgnoreCase))
                    {
                        lock (Authorization)
                        {
                            Authorization.Add(line[14..].Trim());
                        }
                    }
                }
                var payload = Encoding.UTF8.GetBytes(Body);
                var head = $"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {payload.Length}\r\nConnection: close\r\n\r\n";
                await tls.WriteAsync(Encoding.ASCII.GetBytes(head));
                await tls.WriteAsync(payload);
                await tls.FlushAsync();
            }
            catch (Exception)
            {
            }
        }
    }

    public void Dispose()
    {
        _stop.Cancel();
        _listener.Stop();
        _certificate.Dispose();
    }
}
