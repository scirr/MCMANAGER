using Microsoft.Windows.ApplicationModel.Resources;

namespace MCManager.App;

internal static class Strings
{
    private static readonly ResourceLoader? Loader = Create();

    private static ResourceLoader? Create()
    {
        try
        {
            return new ResourceLoader();
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static string Get(string key, string? fallback = null)
    {
        try
        {
            var value = Loader?.GetString(key);
            if (!string.IsNullOrEmpty(value))
            {
                return value;
            }
        }
        catch (Exception)
        {
        }
        return fallback ?? key;
    }

    public static string Origin(string? type)
    {
        if (string.IsNullOrEmpty(type))
        {
            return "";
        }
        return Get("BackupOrigin_" + type.Replace('-', '_'), type);
    }

    public static string EncryptedLabel(bool encrypted) => encrypted ? Get("BackupEncrypted") : "";

    public static string State(string? state)
    {
        if (string.IsNullOrEmpty(state))
        {
            return "";
        }
        return Get("State_" + state.Replace('-', '_'), state);
    }
}
