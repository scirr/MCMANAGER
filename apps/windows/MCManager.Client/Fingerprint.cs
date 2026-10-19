using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace MCManager.Client;

public static class Fingerprint
{
    public static string Format(byte[] der)
    {
        var hex = Convert.ToHexString(SHA256.HashData(der));
        var parts = new string[hex.Length / 2];
        for (var i = 0; i < parts.Length; i++)
        {
            parts[i] = hex.Substring(i * 2, 2);
        }
        return string.Join(':', parts);
    }

    public static string Of(X509Certificate certificate) => Format(certificate.GetRawCertData());

    public static bool IsValid(string? value)
    {
        if (value is null || value.Length != 95)
        {
            return false;
        }
        for (var i = 0; i < value.Length; i++)
        {
            var c = value[i];
            var ok = i % 3 == 2 ? c == ':' : c is (>= '0' and <= '9') or (>= 'A' and <= 'F');
            if (!ok)
            {
                return false;
            }
        }
        return true;
    }

    public static bool Equal(string? left, string? right)
    {
        if (left is null || right is null)
        {
            return false;
        }
        return CryptographicOperations.FixedTimeEquals(
            Encoding.ASCII.GetBytes(left.ToUpperInvariant()),
            Encoding.ASCII.GetBytes(right.ToUpperInvariant()));
    }
}
