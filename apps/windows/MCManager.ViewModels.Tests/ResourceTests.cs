using System.Text.RegularExpressions;
using Xunit;

namespace MCManager.ViewModels.Tests;

public class ResourceTests
{
    private static string StringsDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "MCManager.App", "Strings");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }
            dir = dir.Parent;
        }
        throw new DirectoryNotFoundException("MCManager.App/Strings");
    }

    private static Dictionary<string, string> Load(string language)
    {
        var text = File.ReadAllText(Path.Combine(StringsDir(), language, "Resources.resw"));
        return Regex.Matches(text, "<data name=\"([^\"]+)\"[^>]*><value>(.*?)</value>", RegexOptions.Singleline)
            .ToDictionary(m => m.Groups[1].Value, m => m.Groups[2].Value);
    }

    [Fact]
    public void French_and_english_define_the_same_keys()
    {
        var en = Load("en-US");
        var fr = Load("fr-FR");
        Assert.Empty(en.Keys.Except(fr.Keys));
        Assert.Empty(fr.Keys.Except(en.Keys));
    }

    [Fact]
    public void No_string_is_empty_and_placeholders_match()
    {
        var en = Load("en-US");
        var fr = Load("fr-FR");
        foreach (var (key, value) in en)
        {
            Assert.False(string.IsNullOrWhiteSpace(value), key);
            Assert.False(string.IsNullOrWhiteSpace(fr[key]), key);
            Assert.Equal(Regex.Matches(value, @"\{\d\}").Count, Regex.Matches(fr[key], @"\{\d\}").Count);
        }
    }

    [Fact]
    public void Every_choice_of_a_list_has_a_label()
    {
        var en = Load("en-US");
        var choices = PlayersViewModel.Kinds.Concat(ModsViewModel.Sources).Concat(DatapacksViewModel.Placements)
            .Concat(TasksViewModel.Actions).Concat(SettingsViewModel.Modes).Concat(SettingsViewModel.JoinModes)
            .Concat(AlertsViewModel.Types).Concat(DevicesViewModel.Roles).Concat(RouterViewModel.AccessKinds);
        foreach (var choice in choices)
        {
            Assert.True(en.ContainsKey("Choice_" + choice.Replace('-', '_')), choice);
        }
    }

    [Fact]
    public void Every_error_code_the_tabs_report_is_translated()
    {
        var en = Load("en-US");
        foreach (var code in new[]
        {
            "forbidden", "invalid_radius", "cron_required", "command_required", "invalid_time",
            "name_required", "invalid_ram", "invalid_port", "defines_blocks", "eula_required",
            "invalid_value", "sleep_after_too_short", "sleep_needs_rcon", "unsupported_on_windows",
            "bad_port", "java_unknown_version", "source_required", "bad_type", "bad_events", "bad_channel_name",
            "missing_host", "missing_addresses", "missing_telegram", "missing_topic", "bad_url", "channel_exists",
            "channel_not_found", "no_channel", "alert_test_failed", "router_port_conflict", "router_usage",
            "tls_unavailable", "device_not_found", "device_revoked", "no_previous", "bad_signature", "not_listed",
            "bad_checksum", "unsigned", "no_asset", "downgrade_refused", "unknown_pack", "pack_no_server_files",
            "no_modpack", "pack_not_updatable",
        })
        {
            Assert.True(en.ContainsKey("Error_" + code), code);
        }
    }

    [Fact]
    public void Every_setting_key_has_a_label()
    {
        var en = Load("en-US");
        foreach (var key in SettingsViewModel.Keys)
        {
            Assert.True(en.ContainsKey("Setting_" + key), key);
        }
    }

    [Fact]
    public void Every_alert_event_notification_and_status_has_a_label()
    {
        var en = Load("en-US");
        foreach (var key in AlertsViewModel.EventKeys)
        {
            Assert.True(en.ContainsKey("AlertEvent_" + key), key);
        }
        foreach (var kind in new[] { "crash", "crash_loop", "backup_failed", "join" })
        {
            Assert.True(en.ContainsKey("Notify_" + kind), kind);
        }
        foreach (var level in new[] { "ok", "info", "warn", "err" })
        {
            Assert.True(en.ContainsKey("DoctorLevel_" + level), level);
        }
        foreach (var done in new[]
        {
            "test", "added", "removed", "java_installed", "java_removed", "remote_on", "remote_off", "code", "role", "revoked",
            "update", "rollback", "doctor", "router_on", "router_off", "route", "route_removed", "default", "access",
            "modpack", "modpack_current",
        })
        {
            Assert.True(en.ContainsKey("Done_" + done), done);
        }
    }
}
