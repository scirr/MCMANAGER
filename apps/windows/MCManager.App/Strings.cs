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

    public static string Done(string? key) => Keyed("Done_", key);

    public static string Choice(string? value) => Keyed("Choice_", value);

    public static string AlertEvent(string? key) => key == "*" ? Get("AlertEventAll") : Keyed("AlertEvent_", key);

    public static string AlertEvents(string? csv)
        => string.IsNullOrEmpty(csv) ? Get("AlertEventAll") : string.Join(", ", csv.Split(',').Select(AlertEvent));

    public static string AlertLegacy(bool legacy) => legacy ? Get("AlertLegacy") : "";

    public static string JavaRuntime(string? major) => string.Format(Get("JavaRuntime"), major);

    public static string JavaUsedBy(string? servers)
        => string.IsNullOrEmpty(servers) ? Get("JavaUnused") : string.Format(Get("JavaUsedBy"), servers);

    public static string DeviceDetail(string? ip, string? seen, string? servers)
    {
        var parts = new List<string>();
        if (!string.IsNullOrEmpty(ip))
        {
            parts.Add(ip);
        }
        parts.Add(string.IsNullOrEmpty(seen) ? Get("DeviceNeverSeen") : string.Format(Get("DeviceLastSeen"), seen));
        if (!string.IsNullOrEmpty(servers))
        {
            parts.Add(servers);
        }
        return string.Join(" - ", parts);
    }

    public static string AuditLine(string? at, string? device, string? server, bool ok)
    {
        var parts = new List<string>();
        foreach (var part in new[] { at, device, server })
        {
            if (!string.IsNullOrEmpty(part))
            {
                parts.Add(part);
            }
        }
        if (!ok)
        {
            parts.Add(Get("AuditRefused"));
        }
        return string.Join(" - ", parts);
    }

    public static string PairCode(string? code, int minutes)
        => string.IsNullOrEmpty(code) ? "" : string.Format(Get("PairCodeValue"), code, minutes);

    public static string UpdateStatus(string? current, string? latest, bool available)
        => string.IsNullOrEmpty(current) ? "" : string.Format(Get(available ? "UpdateAvailable" : "UpdateCurrent"), current, latest);

    public static string DoctorLevel(string? level) => Keyed("DoctorLevel_", level);

    public static string DoctorTitle(string? server, string? name)
        => string.IsNullOrEmpty(server) ? name ?? "" : server + " - " + name;

    public static string DoctorFix(string? fix) => string.IsNullOrEmpty(fix) ? "" : string.Format(Get("DoctorFix"), fix);

    public static string DoctorSummary(bool hasRun, int errors, int warnings)
    {
        if (!hasRun)
        {
            return "";
        }
        if (errors > 0)
        {
            return string.Format(Get("DoctorErrors"), errors);
        }
        return warnings > 0 ? string.Format(Get("DoctorWarnings"), warnings) : Get("DoctorClean");
    }

    public static string RouterPending(string? pending)
        => string.IsNullOrEmpty(pending) ? "" : string.Format(Get("RouterPending"), pending);

    public static string NotifyTitle(string kind, string? server) => string.Format(Get("Notify_" + kind, kind), server);
}
