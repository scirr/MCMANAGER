using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class SettingItem : ObservableObject
{
    public SettingItem(string key, bool isSecret, bool isSet, string original)
    {
        Key = key;
        IsSecret = isSecret;
        IsSet = isSet;
        Original = original;
        _value = original;
    }

    public string Key { get; }

    public bool IsSecret { get; }

    public bool IsSet { get; }

    public string Original { get; }

    [ObservableProperty]
    private string _value;

    public bool IsPlain => !IsSecret;

    public bool IsChanged => IsSecret ? Value.Length > 0 : Value.Trim() != Original;
}

public sealed partial class SettingsViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Keys = new[]
    {
        "nom_serveur", "port", "rcon_port", "ram_allocation", "cpu_affinity", "jar_name", "domaine",
        "dossier_backup", "backup_retention_days", "backup_keep", "stop_timeout",
        "internal_port", "metrics_bind", "metrics_allow_remote",
        "sleep_freeze", "sleep_hold_timeout", "sleep_join_mode", "sleep_proxy_protocol",
        "mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file",
    };

    public static readonly IReadOnlyList<string> SecretKeys = new[]
    {
        "mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file", "alerts", "backup_remotes",
    };

    public static readonly IReadOnlyList<string> Modes = new[] { "schedule", "always-on", "maintenance" };

    public const string SystemJava = "system";

    public SettingsViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
    }

    public ObservableCollection<SettingItem> Items { get; } = new();

    public ObservableCollection<string> JavaChoices { get; } = new();

    [ObservableProperty]
    private string _mode = "";

    [ObservableProperty]
    private string _openTime = "";

    [ObservableProperty]
    private string _closeTime = "";

    [ObservableProperty]
    private string _javaChoice = "";

    private string _loadedJava = "";

    private static string Text(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString() ?? "",
        JsonValueKind.Number => value.GetRawText(),
        JsonValueKind.True => "1",
        JsonValueKind.False => "0",
        JsonValueKind.Null or JsonValueKind.Undefined => "",
        _ => value.GetRawText(),
    };

    private static int Int(IReadOnlyDictionary<string, JsonElement> config, string key)
        => config.TryGetValue(key, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) ? number : 0;

    private static string Clock(int hour, int minute)
        => hour.ToString("00", CultureInfo.InvariantCulture) + ":" + minute.ToString("00", CultureInfo.InvariantCulture);

    public static bool TryParseClock(string text, out int hour, out int minute)
    {
        hour = 0;
        minute = 0;
        var parts = text.Trim().Split(':');
        return parts.Length == 2
            && int.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out hour)
            && int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out minute)
            && hour is >= 0 and <= 23
            && minute is >= 0 and <= 59;
    }

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await Errors.TryAsync(async () =>
        {
            var document = await Api.GetServerConfigAsync(Server);
            var configured = document.SecretsSet.ToHashSet();
            Items.Clear();
            foreach (var key in Keys)
            {
                var secret = SecretKeys.Contains(key);
                if (secret)
                {
                    Items.Add(new SettingItem(key, true, configured.Contains(key), ""));
                }
                else if (document.Config.TryGetValue(key, out var value))
                {
                    Items.Add(new SettingItem(key, false, true, Text(value)));
                }
            }
            OpenTime = Clock(Int(document.Config, "heure_ouverture"), Int(document.Config, "minute_ouverture"));
            CloseTime = Clock(Int(document.Config, "heure_fermeture"), Int(document.Config, "minute_fermeture"));
            var snapshot = await Api.GetServerAsync(Server);
            Mode = snapshot.Mode ?? "";
            var java = await Api.ListServerJavaAsync(Server);
            JavaChoices.Clear();
            JavaChoices.Add(SystemJava);
            foreach (var major in java.Runtimes.Keys.OrderBy(k => int.TryParse(k, out var n) ? n : int.MaxValue))
            {
                JavaChoices.Add(major);
            }
            _loadedJava = java.Servers.FirstOrDefault(s => s.Server == Server)?.JavaText ?? SystemJava;
            JavaChoice = _loadedJava;
        });
    }

    [RelayCommand]
    public async Task SaveAsync()
    {
        var changed = Items.Where(i => i.IsChanged).ToList();
        if (changed.Count == 0)
        {
            return;
        }
        var ok = await WriteAsync(async () =>
        {
            foreach (var item in changed)
            {
                var result = await Api.SetConfigValueAsync(Server, item.Key, item.IsSecret ? item.Value : item.Value.Trim());
                if (result.RestartRequired)
                {
                    RestartRequired = true;
                }
            }
        });
        if (ok)
        {
            LastDone = "save";
        }
        await RefreshAsync();
    }

    public async Task SetModeAsync(string mode)
    {
        if (!Modes.Contains(mode) || mode == Mode)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.SetServerModeAsync(Server, mode)))
        {
            Mode = mode;
            LastDone = "mode";
        }
        else
        {
            await RefreshAsync();
        }
    }

    [RelayCommand]
    public async Task SaveScheduleAsync()
    {
        if (!TryParseClock(OpenTime, out var openHour, out var openMinute)
            || !TryParseClock(CloseTime, out var closeHour, out var closeMinute))
        {
            Errors.Show("invalid_time", "");
            return;
        }
        var schedule = new ScheduleRequest { OpenHour = openHour, OpenMinute = openMinute, CloseHour = closeHour, CloseMinute = closeMinute };
        if (await WriteAsync(async () => await Api.SetServerScheduleAsync(Server, schedule)))
        {
            LastDone = "schedule";
        }
    }

    [RelayCommand]
    public async Task SaveJavaAsync()
    {
        if (JavaChoice.Length == 0 || JavaChoice == _loadedJava)
        {
            return;
        }
        var choice = JavaChoice;
        var ok = await WriteAsync(async () =>
        {
            var used = await Api.SetServerJavaAsync(Server, choice);
            if (used.RestartRequired)
            {
                RestartRequired = true;
            }
        });
        if (ok)
        {
            _loadedJava = choice;
            LastDone = "java";
        }
    }
}
