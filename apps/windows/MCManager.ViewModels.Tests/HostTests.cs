using System.Text.Json;
using MCManager.Client;
using Xunit;

namespace MCManager.ViewModels.Tests;

public class HostTests
{
    private static Job Done() => new() { Id = "jx", State = "succeeded" };

    [Fact]
    public async Task Alerts_refresh_lists_channels_with_their_target()
    {
        var client = new FakeClient();
        client.Alerts.Add(new AlertChannel { Name = "ntfy-1", Type = "ntfy", Topic = "mc", Events = new List<string> { "crash", "*" } });
        client.Alerts.Add(new AlertChannel { Name = "legacy", Type = "discord", Legacy = true });
        var vm = new AlertsViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        Assert.Equal(2, vm.Items.Count);
        Assert.Equal("mc", vm.Items[0].Target);
        Assert.Equal("crash,*", vm.Items[0].Events);
        Assert.True(vm.Items[0].CanRemove);
        Assert.False(vm.Items[1].CanRemove);
    }

    [Fact]
    public async Task Alerts_add_sends_only_the_fields_of_the_type_and_clears_secrets()
    {
        var client = new FakeClient();
        var vm = new AlertsViewModel(client, new ErrorReporter(), "survie")
        {
            NewType = "telegram",
            NewName = " bot ",
            NewToken = " secret-token ",
            NewChatId = "42",
            NewHost = "ignored.example",
        };
        vm.EventChoices.First(e => e.Key == "crash").IsSelected = true;
        vm.EventChoices.First(e => e.Key == "stop").IsSelected = true;

        await vm.AddAsync();

        var request = client.AlertRequest!;
        Assert.Equal("telegram", request.Type);
        Assert.Equal("stop,crash", request.Events);
        Assert.Equal("bot", request.Name);
        Assert.Equal("secret-token", request.Token);
        Assert.Equal("42", request.ChatId);
        Assert.Null(request.Host);
        Assert.Equal("", vm.NewToken);
        Assert.Equal("added", vm.LastDone);
        Assert.Single(vm.Items);
    }

    [Fact]
    public async Task Alerts_add_refuses_a_bad_port_without_calling_the_api()
    {
        var client = new FakeClient();
        var errors = new ErrorReporter();
        var vm = new AlertsViewModel(client, errors, "survie") { NewType = "email", NewPort = "70000" };

        await vm.AddAsync();

        Assert.Equal("bad_port", errors.Code);
        Assert.Empty(client.Calls);
    }

    [Fact]
    public void Alerts_form_shows_the_fields_of_the_selected_type()
    {
        var vm = new AlertsViewModel(new FakeClient(), new ErrorReporter(), "survie");
        Assert.True(vm.ShowHost);
        Assert.True(vm.ShowPassword);
        Assert.False(vm.ShowUrl);
        vm.NewType = "discord";
        Assert.True(vm.ShowUrl);
        Assert.False(vm.ShowHost);
        Assert.False(vm.ShowSecret);
    }

    [Fact]
    public async Task Alerts_remove_needs_the_confirmation_and_test_targets_a_channel()
    {
        var client = new FakeClient();
        client.Alerts.Add(new AlertChannel { Name = "a", Type = "discord" });
        var vm = new AlertsViewModel(client, new ErrorReporter(), "survie");

        await vm.RemoveAsync("a", false);
        Assert.Empty(client.Calls);
        await vm.TestAsync("a");
        Assert.Equal("alert-test a", client.Calls[0]);
        Assert.Equal("test", vm.LastDone);
        await vm.RemoveAsync("a", true);
        Assert.Contains("alert-remove a", client.Calls);
        Assert.Empty(vm.Items);
    }

    [Fact]
    public async Task Alerts_a_403_hides_the_row_buttons()
    {
        var client = new FakeClient();
        client.Alerts.Add(new AlertChannel { Name = "a", Type = "discord" });
        var vm = new AlertsViewModel(client, new ErrorReporter(), "survie");
        await vm.RefreshAsync();
        Assert.True(vm.Items[0].CanWrite);

        client.Failure = new ApiException("forbidden", "", 403);
        await vm.TestAsync("a");

        Assert.True(vm.IsReadOnly);
        Assert.False(vm.Items[0].CanWrite);
    }

    [Fact]
    public async Task Java_lists_runtimes_with_their_servers_and_the_versions_left_to_install()
    {
        var client = new FakeClient();
        client.JavaRuntimesFound["21"] = "/j/21";
        client.JavaRuntimesFound["8"] = "/j/8";
        client.ServerJava = "21";
        var vm = new JavaViewModel(client, new ErrorReporter());

        await vm.RefreshAsync();

        Assert.Equal(new[] { "8", "21" }, vm.Items.Select(i => i.Major));
        Assert.Equal("", vm.Items[0].Servers);
        Assert.Equal(new[] { "11", "17", "25" }, vm.Installable);
        Assert.Equal("11", vm.SelectedMajor);
    }

    [Fact]
    public async Task Java_install_follows_the_job_and_reloads()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(Done());
        var vm = new JavaViewModel(client, new ErrorReporter()) { JobPollInterval = TimeSpan.Zero, SelectedMajor = "17" };

        await vm.InstallAsync();

        Assert.Equal("java-install 17", client.Calls[0]);
        Assert.Equal("java_installed", vm.LastDone);
        Assert.Contains(vm.Items, i => i.Major == "17");
        Assert.DoesNotContain("17", vm.Installable);
    }

    [Fact]
    public async Task Java_remove_needs_the_confirmation()
    {
        var client = new FakeClient();
        client.JavaRuntimesFound["17"] = "/j/17";
        var vm = new JavaViewModel(client, new ErrorReporter());

        await vm.RemoveAsync("17", false);
        Assert.Empty(client.Calls);
        await vm.RemoveAsync("17", true);
        Assert.Contains("java-remove 17", client.Calls);
    }

    [Fact]
    public async Task Devices_refresh_loads_devices_status_and_audit_and_skips_revoked()
    {
        var client = new FakeClient();
        client.Devices.Add(new DeviceEntry { Id = "d1", Name = "Phone", Roles = new DeviceRoles { Default = "operator" }, LastIp = "1.2.3.4", LastSeen = "2026-10-01T10:00:00" });
        client.Devices.Add(new DeviceEntry { Id = "d2", Name = "Old", Revoked = true });
        client.AuditLog.Add(new AuditEntry { At = "2026-10-01T10:00:01", Action = "stop", Device = "Phone", Ok = false });
        var vm = new DevicesViewModel(client, new ErrorReporter());

        await vm.RefreshAsync();

        var device = Assert.Single(vm.Items);
        Assert.Equal("operator", device.Role);
        Assert.Equal("2026-10-01 10:00:00", device.LastSeen);
        Assert.Equal("AB:CD", vm.Fingerprint);
        Assert.Equal("2026-10-01 10:00:01", Assert.Single(vm.Audit).At);
        Assert.False(vm.Audit[0].Ok);
    }

    [Fact]
    public async Task Devices_remote_switch_and_pairing_code()
    {
        var client = new FakeClient();
        var vm = new DevicesViewModel(client, new ErrorReporter()) { PairName = " tablet ", PairRole = "viewer" };

        await vm.SetRemoteAsync(false);
        Assert.DoesNotContain("remote-set False", client.Calls);
        await vm.SetRemoteAsync(true);
        Assert.True(vm.RemoteEnabled);
        await vm.NewCodeAsync();

        Assert.Contains("pair-code viewer tablet", client.Calls);
        Assert.Equal("ABCD-1234", vm.Code);
        Assert.Equal(5, vm.CodeMinutes);
        Assert.True(vm.HasCode);
    }

    [Fact]
    public async Task Devices_role_change_and_revoke()
    {
        var client = new FakeClient();
        client.Devices.Add(new DeviceEntry { Id = "d1", Name = "Phone", Roles = new DeviceRoles { Default = "viewer" } });
        var vm = new DevicesViewModel(client, new ErrorReporter());
        await vm.RefreshAsync();

        await vm.SetRoleAsync("d1", "viewer");
        Assert.DoesNotContain("device-role d1 viewer", client.Calls);
        await vm.SetRoleAsync("d1", "admin");
        Assert.Equal("admin", vm.Items[0].Role);
        await vm.RevokeAsync("d1", false);
        Assert.NotEmpty(vm.Items);
        await vm.RevokeAsync("d1", true);
        Assert.Empty(vm.Items);
        Assert.Equal("revoked", vm.LastDone);
    }

    [Fact]
    public async Task Devices_pairing_code_from_a_remote_device_marks_the_panel_read_only()
    {
        var client = new FakeClient();
        var vm = new DevicesViewModel(client, new ErrorReporter());
        client.Failure = new ApiException("forbidden", "", 403);

        await vm.NewCodeAsync();

        Assert.True(vm.IsReadOnly);
        Assert.False(vm.HasCode);
    }

    [Fact]
    public async Task Update_checks_applies_with_confirmation_and_rolls_back()
    {
        var client = new FakeClient { Update = new UpdateInfo { Ok = true, Current = "3.0.0", Latest = "3.1.0", UpdateAvailable = true } };
        client.StartedJobs.Enqueue(Done());
        var vm = new UpdateViewModel(client, new ErrorReporter()) { JobPollInterval = TimeSpan.Zero };
        await vm.RefreshAsync();

        Assert.True(vm.CanApply);
        Assert.False(vm.CanRollback);
        await vm.ApplyAsync(false);
        Assert.DoesNotContain("update-apply", client.Calls);
        await vm.ApplyAsync(true);

        Assert.Equal("3.1.0", vm.Current);
        Assert.False(vm.Available);
        Assert.True(vm.CanRollback);
        await vm.RollbackAsync(true);
        Assert.Contains("update-rollback", client.Calls);
        Assert.False(vm.RollbackAvailable);
    }

    [Fact]
    public async Task Doctor_runs_and_counts_the_findings()
    {
        var client = new FakeClient
        {
            Doctor = new DoctorReport
            {
                Ok = true,
                Errors = 1,
                Warnings = 2,
                Checks = new List<DoctorCheck>
                {
                    new() { Name = "java", Ok = true, Level = "ok", Detail = "17" },
                    new() { Server = "survie", Name = "port", Ok = false, Detail = "taken", Fix = "change it" },
                },
            },
        };
        var vm = new DoctorViewModel(client, new ErrorReporter());

        await vm.RunAsync();

        Assert.True(vm.HasRun);
        Assert.Equal(1, vm.ErrorCount);
        Assert.Equal(2, vm.WarningCount);
        Assert.Equal("err", vm.Items[1].Level);
        Assert.Equal("change it", vm.Items[1].Fix);
        Assert.False(vm.IsBusy);
    }

    private static FakeClient RouterClient()
    {
        var client = new FakeClient();
        client.Servers.Add(new ServerSnapshot { Name = "a" });
        client.Servers.Add(new ServerSnapshot { Name = "b" });
        return client;
    }

    [Fact]
    public async Task Router_refresh_loads_routes_access_and_server_names()
    {
        var client = RouterClient();
        client.Router = new RouterDocument
        {
            Ok = true,
            PendingRestart = new List<string> { "a" },
            Config = new RouterConfig
            {
                Enabled = true,
                Default = "b",
                Routes = new Dictionary<string, string> { ["z.example"] = "a", ["m.example"] = "b" },
                Allow = new List<string> { "10.0.0.0/8" },
                Deny = new List<string> { "1.2.3.0/24" },
            },
        };
        var vm = new RouterViewModel(client, new ErrorReporter());

        await vm.RefreshAsync();

        Assert.True(vm.Enabled);
        Assert.Equal("b", vm.DefaultServer);
        Assert.Equal("a", vm.Pending);
        Assert.Equal(new[] { "m.example", "z.example" }, vm.Routes.Select(r => r.Host));
        Assert.Equal(new[] { "allow", "deny" }, vm.Access.Select(a => a.Kind));
        Assert.Equal(new[] { "a", "b" }, vm.ServerNames);
        Assert.Equal("a", vm.NewServer);
    }

    [Fact]
    public async Task Router_toggle_route_default_and_access()
    {
        var client = RouterClient();
        var vm = new RouterViewModel(client, new ErrorReporter());
        await vm.RefreshAsync();

        await vm.ToggleAsync(false);
        Assert.DoesNotContain("router-enabled False", client.Calls);
        await vm.ToggleAsync(true);
        Assert.True(vm.Enabled);

        vm.NewHost = " Play.Example ";
        vm.NewServer = "b";
        await vm.AddRouteAsync();
        Assert.Contains("router-route play.example b", client.Calls);
        Assert.Equal("", vm.NewHost);
        Assert.Single(vm.Routes);

        await vm.SetDefaultAsync("a");
        Assert.Equal("a", vm.DefaultServer);
        await vm.SetDefaultAsync("unknown");
        Assert.DoesNotContain("router-default unknown", client.Calls);

        vm.NewCidr = " 10.0.0.0/8 ";
        await vm.AddAccessAsync();
        Assert.Contains("router-access allow add 10.0.0.0/8", client.Calls);
        Assert.Single(vm.Access);
        await vm.EditAccessAsync("allow", "remove", "10.0.0.0/8");
        Assert.Empty(vm.Access);

        await vm.RemoveRouteAsync("play.example", false);
        Assert.Single(vm.Routes);
        await vm.RemoveRouteAsync("play.example", true);
        Assert.Empty(vm.Routes);
    }

    [Fact]
    public async Task Router_refuses_a_route_without_host_or_known_server()
    {
        var client = RouterClient();
        var errors = new ErrorReporter();
        var vm = new RouterViewModel(client, errors);
        await vm.RefreshAsync();
        client.Calls.Clear();

        vm.NewHost = "  ";
        await vm.AddRouteAsync();

        Assert.Equal("invalid_value", errors.Code);
        Assert.Empty(client.Calls);
    }

    [Fact]
    public async Task Mods_update_modpack_flags_a_restart_or_reports_up_to_date()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(new Job { Id = "jx", State = "succeeded", Result = new JobResult { Ok = true, Code = "pack_updated" } });
        var vm = new ModsViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.UpdateModpackAsync();

        Assert.Equal("modpack-update survie", client.Calls[0]);
        Assert.Equal("modpack", vm.LastDone);
        Assert.True(vm.RestartRequired);

        client.StartedJobs.Enqueue(new Job { Id = "jy", State = "succeeded", Result = new JobResult { Ok = true, Code = "pack_up_to_date" } });
        var current = new ModsViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };
        await current.UpdateModpackAsync();
        Assert.Equal("modpack_current", current.LastDone);
        Assert.False(current.RestartRequired);
    }

    [Fact]
    public async Task Create_by_modpack_name_looks_it_up_and_installs_it()
    {
        var client = new FakeClient { Pack = new ModpackInfo { Ok = true, Title = "All the Mods", Version = "1.2", McVersion = "1.21.1", Loader = "neoforge" } };
        client.StartedJobs.Enqueue(new Job { Id = "jx", State = "succeeded", Server = "atm" });
        var vm = new CreateServerViewModel(client, new ErrorReporter()) { JobPollInterval = TimeSpan.Zero, ModpackSource = " all-the-mods ", Ram = "6g" };
        Assert.True(vm.IsModpack);
        Assert.False(vm.ShowLoader);

        await vm.LookupModpackAsync();
        Assert.Equal("All the Mods - 1.2 - 1.21.1 - neoforge", vm.PackInfo);
        vm.Next();
        vm.Next();
        Assert.Equal(CreateServerViewModel.LastStep, vm.Step);
        vm.AcceptEula = true;
        await vm.CreateAsync();

        Assert.Equal("all-the-mods", client.PackInstalled!.Source);
        Assert.True(client.PackInstalled.AcceptEula);
        Assert.Null(client.PackInstalled.Name);
        Assert.Equal("6G", client.PackInstalled.Ram);
        Assert.Equal("atm", vm.CreatedName);
    }

    [Fact]
    public async Task Create_by_modpack_needs_a_source_to_look_up()
    {
        var errors = new ErrorReporter();
        var vm = new CreateServerViewModel(new FakeClient(), errors);
        await vm.LookupModpackAsync();
        Assert.Equal("source_required", errors.Code);
    }

    [Fact]
    public void Editing_the_modpack_source_clears_the_found_info()
    {
        var vm = new CreateServerViewModel(new FakeClient(), new ErrorReporter()) { ModpackSource = "a", PackInfo = "x" };
        Assert.True(vm.HasPackInfo);
        vm.ModpackSource = "b";
        Assert.False(vm.HasPackInfo);
    }

    [Fact]
    public void Main_has_the_host_panels_only_when_connected()
    {
        Assert.NotNull(new MainViewModel(new FakeClient(), new ErrorReporter()).Host);
        Assert.Null(new MainViewModel(null, new ErrorReporter()).Host);
    }

    private static NotificationPrefs All() => new();

    [Fact]
    public void Notifications_map_crash_backup_failure_and_joins()
    {
        var prefs = All();

        var crash = prefs.NoticeFor("""{"type":"alert","server":"survie","event":"crash","detail":"exit 1"}""");
        Assert.Equal(new AppNotice("crash", "survie", "exit 1"), crash);
        Assert.Equal("crash-survie", crash!.Id);
        Assert.Equal("crash_loop", prefs.NoticeFor("""{"type":"alert","server":"s","event":"crash_loop"}""")!.Kind);
        Assert.Equal("backup_failed", prefs.NoticeFor("""{"type":"alert","server":"s","event":"backup_failed","detail":"disk"}""")!.Kind);
        var join = prefs.NoticeFor("""{"type":"players","server":"s","joined":["Alex","Steve"],"online":2}""");
        Assert.Equal(new AppNotice("join", "s", "Alex, Steve"), join);
    }

    [Fact]
    public void Notifications_ignore_other_events_noise_and_empty_joins()
    {
        var prefs = All();
        Assert.Null(prefs.NoticeFor("""{"type":"state","server":"s","state":"running"}"""));
        Assert.Null(prefs.NoticeFor("""{"type":"alert","server":"s","event":"start"}"""));
        Assert.Null(prefs.NoticeFor("""{"type":"players","server":"s","joined":[]}"""));
        Assert.Null(prefs.NoticeFor("""{"type":"players","server":"s","online":1}"""));
        Assert.Null(prefs.NoticeFor("not json"));
        Assert.Null(prefs.NoticeFor(""));
        Assert.Null(prefs.NoticeFor("[1]"));
    }

    [Fact]
    public void Notifications_respect_the_preferences_and_save_changes()
    {
        IReadOnlyDictionary<string, bool>? saved = null;
        var prefs = new NotificationPrefs(new Dictionary<string, bool> { ["join"] = false }, value => saved = value);
        Assert.True(prefs.Crash);
        Assert.False(prefs.Join);
        Assert.Null(saved);
        Assert.Null(prefs.NoticeFor("""{"type":"players","server":"s","joined":["Alex"]}"""));

        prefs.Crash = false;

        Assert.False(saved!["crash"]);
        Assert.True(saved["backup_failed"]);
        Assert.Null(prefs.NoticeFor("""{"type":"alert","server":"s","event":"crash"}"""));
        Assert.NotNull(prefs.NoticeFor("""{"type":"alert","server":"s","event":"backup_failed"}"""));
    }

    [Fact]
    public async Task Event_watcher_delivers_the_notices_of_the_stream()
    {
        var client = new FakeClient();
        client.Events.Add(new ConsoleEvent("1", "message", """{"type":"state","server":"s","state":"running"}"""));
        client.Events.Add(new ConsoleEvent("2", "message", """{"type":"alert","server":"s","event":"crash","detail":"x"}"""));
        var delivered = new List<AppNotice>();
        var watcher = new EventWatcher(client, All(), delivered.Add);

        await watcher.ConsumeAsync(CancellationToken.None);

        Assert.Equal("crash", Assert.Single(delivered).Kind);
    }

    [Fact]
    public async Task Event_watcher_survives_a_failing_stream()
    {
        var client = new FakeClient { Failure = new ApiException("daemon_unreachable", "", 0) };
        var watcher = new EventWatcher(client, All(), _ => { });

        await watcher.ConsumeAsync(CancellationToken.None);

        Assert.Equal("events", client.Calls[0]);
    }
}
