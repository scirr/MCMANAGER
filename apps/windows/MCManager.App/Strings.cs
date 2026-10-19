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

    private static string Keyed(string prefix, string? value)
        => string.IsNullOrEmpty(value) ? "" : Get(prefix + value.Replace('-', '_'), value);

    public static string ModFlags(bool addsBlocks) => addsBlocks ? Get("ModAddsBlocks") : "";

    public static string EnabledState(bool enabled) => Get(enabled ? "StateEnabled" : "StateDisabled");

    public static string ToggleLabel(bool enabled) => Get(enabled ? "ActionDisable" : "ActionEnable");

    public static string DatapackProblem(string? problem) => Keyed("DatapackProblem_", problem);

    public static string Dimension(string? id) => Keyed("Dimension_", id);

    public static string TaskAction(string? action) => Keyed("TaskAction_", action);

    public static string NextRun(string? when)
        => string.IsNullOrEmpty(when) ? "" : string.Format(Get("TaskNextRun"), when);

    public static string LastResult(string? result)
        => string.IsNullOrEmpty(result) ? "" : result == "ok" ? Get("TaskLastOk") : string.Format(Get("TaskLastFailed"), Get("Error_" + result, result));

    public static string Setting(string? key) => Keyed("Setting_", key);

    public static string SecretState(bool secret, bool isSet)
        => secret ? Get(isSet ? "SecretIsSet" : "SecretNotSet") : "";

    public static string WizardStep(int step) => Get("WizardStep_" + step);
}
