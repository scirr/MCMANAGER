using System.Net.Security;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;

namespace MCManager.Client;

public static class PinnedHttpHandler
{
    public static HttpClientHandler Create(string? pinnedFingerprint)
    {
        var pin = pinnedFingerprint;
        return new HttpClientHandler
        {
            SslProtocols = SslProtocols.Tls13,
            UseProxy = false,
            AllowAutoRedirect = false,
            ServerCertificateCustomValidationCallback = (_, certificate, _, _) => Accepts(pin, certificate),
        };
    }

    public static bool Accepts(string? pinnedFingerprint, X509Certificate? presented)
    {
        if (presented is null || !Fingerprint.IsValid(pinnedFingerprint))
        {
            return false;
        }
        return Fingerprint.Equal(pinnedFingerprint, Fingerprint.Of(presented));
    }
}
