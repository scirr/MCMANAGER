using System.Text.Json;
using MCManager.Client;
using Xunit;

namespace MCManager.ViewModels.Tests;

public class TabsTests
{
    private static Job Done() => new() { Id = "jx", State = "succeeded" };

    private static JsonElement Json(string raw) => JsonDocument.Parse(raw).RootElement;

    [Fact]
    public async Task Mods_refresh_lists_name_version_and_source()
    {
        var client = new FakeClient();
        client.Mods.Add(new ModEntry { File = "lithium.jar", Id = "lithium", Name = "Lithium", Version = "0.13", Source = "modrinth", AddsBlocks = false });
        client.Mods.Add(new ModEntry { File = "x.jar", Id = "x" });
        var vm = new ModsViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        Assert.Equal(2, vm.Items.Count);
        Assert.Equal("Lithium", vm.Items[0].Name);
        Assert.Equal("0.13", vm.Items[0].Version);
        Assert.Equal("x", vm.Items[1].Name);
        Assert.False(vm.IsEmpty);
    }

    [Fact]
    public async Task Mods_add_runs_the_job_flags_a_restart_and_reloads()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(Done());
        var vm = new ModsViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero, NewReference = " lithium ", SelectedSource = "modrinth" };

        await vm.AddAsync();

        Assert.Equal("add-mod lithium modrinth", client.Calls[0]);
        Assert.Equal("add", vm.LastDone);
        Assert.True(vm.RestartRequired);
        Assert.Equal("", vm.NewReference);
        Assert.Contains("mods survie", client.Calls);
    }

    [Fact]
    public async Task Mods_add_ignores_an_empty_reference()
    {
        var client = new FakeClient();
        var vm = new ModsViewModel(client, new ErrorReporter(), "survie");

        await vm.AddAsync();

        Assert.Empty(client.Calls);
    }

    [Fact]
    public async Task Mods_remove_needs_the_confirmation_and_passes_the_block_flag()
    {
        var client = new FakeClient();
        client.Mods.Add(new ModEntry { File = "cobble.jar", Name = "Cobble", AddsBlocks = true });
        var vm = new ModsViewModel(client, new ErrorReporter(), "survie");
        await vm.RefreshAsync();
        client.Calls.Clear();

        await vm.RemoveAsync("cobble.jar", false);
        Assert.Empty(client.Calls);

        await vm.RemoveAsync("cobble.jar", true);
        Assert.Equal("remove-mod cobble.jar True", client.Calls[0]);
        Assert.True(vm.RestartRequired);
        Assert.Empty(vm.Items);
        Assert.True(vm.IsEmpty);
    }

    [Fact]
    public async Task Mods_forbidden_write_turns_the_tab_read_only()
    {
        var client = new FakeClient();
        client.Mods.Add(new ModEntry { File = "a.jar" });
        var errors = new ErrorReporter();
        var vm = new ModsViewModel(client, errors, "survie");
        await vm.RefreshAsync();
        Assert.True(vm.CanWrite);
        client.Failure = new ApiException("forbidden", "no", 403);

        await vm.RemoveAsync("a.jar", true);

        Assert.True(vm.IsReadOnly);
        Assert.False(vm.CanWrite);
        Assert.False(vm.CanAct);
        Assert.Equal("forbidden", errors.Code);
    }

    [Fact]
    public async Task Mods_update_all_follows_the_job()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(new Job { Id = "ju", State = "running" });
        client.JobStates.Enqueue(new Job { Id = "ju", State = "succeeded", Progress = 100 });
        var vm = new ModsViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.UpdateAllAsync();

        Assert.Contains("update-mods", client.Calls);
        Assert.Equal("update", vm.LastDone);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Mods_failed_job_is_reported_by_code()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(new Job { Id = "j", State = "failed", Result = new JobResult { Code = "mod_not_found" } });
        var errors = new ErrorReporter();
        var vm = new ModsViewModel(client, errors, "survie") { JobPollInterval = TimeSpan.Zero, NewReference = "nope" };

        await vm.AddAsync();

        Assert.Equal("mod_not_found", errors.Code);
        Assert.Equal("", vm.LastDone);
        Assert.Equal("nope", vm.NewReference);
    }

    [Fact]
    public async Task Datapacks_list_and_toggle()
    {
        var client = new FakeClient { PacksRunning = true, RestartNeeded = true };
        client.Packs.Add(new DatapackEntry { Id = "file/a.zip", File = "a.zip", Enabled = false });
        client.Packs.Add(new DatapackEntry { Id = "file/b.zip", File = "b.zip", Enabled = null, Problem = "nested" });
        var vm = new DatapacksViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();
        Assert.True(vm.ServerRunning);
        Assert.True(vm.Items[0].CanToggle);
        Assert.False(vm.Items[1].CanToggle);
        Assert.Equal("nested", vm.Items[1].Problem);

        await vm.SetEnabledAsync("a.zip", true);

        Assert.Contains("datapack a.zip True", client.Calls);
        Assert.True(vm.Items[0].Enabled);
        Assert.True(vm.RestartRequired);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task World_lists_dimensions_and_pregen_progress()
    {
        var client = new FakeClient { PregenReply = "11.2%" };
        client.Dimensions.Add(new WorldDimension { Id = "overworld", SizeBytes = 1610612736 });
        client.Dimensions.Add(new WorldDimension { Id = "nether", SizeBytes = 536870912 });
        var vm = new WorldViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        Assert.Equal("overworld", vm.Dimensions[0].Id);
        Assert.Equal("1.5 GB", vm.Dimensions[0].SizeText);
        Assert.Equal("2.0 GB", vm.TotalSizeText);
        Assert.Equal("11.2%", vm.PregenText);
    }

    [Fact]
    public async Task World_pregen_status_unavailable_is_not_an_error()
    {
        var client = new FakeClient { PregenFailure = new ApiException("server_offline", "", 409) };
        var errors = new ErrorReporter();
        var vm = new WorldViewModel(client, errors, "survie") { PregenText = "old" };

        await vm.RefreshPregenAsync();

        Assert.Equal("", vm.PregenText);
        Assert.False(errors.IsOpen);
    }

    [Fact]
    public async Task World_start_pregen_validates_the_radius()
    {
        var client = new FakeClient();
        var errors = new ErrorReporter();
        var vm = new WorldViewModel(client, errors, "survie") { RadiusText = "abc" };

        await vm.StartPregenAsync();
        Assert.Empty(client.Calls);
        Assert.Equal("invalid_radius", errors.Code);

        vm.RadiusText = "3000";
        vm.CenterText = "0,0";
        await vm.StartPregenAsync();
        Assert.Equal("pregen 3000 0,0", client.Calls[0]);
        Assert.Equal("Task running.", vm.PregenText);
    }

    [Fact]
    public async Task World_reset_needs_the_confirmation()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(Done());
        client.StartedJobs.Enqueue(Done());
        var vm = new WorldViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.ResetAsync("nether", false);
        Assert.Empty(client.Calls);

        await vm.ResetAsync("nether", true);
        Assert.Equal("reset nether True False", client.Calls[0]);
        Assert.Equal("reset", vm.LastDone);

        await vm.ResetAsync("overworld", true);
        Assert.Contains("reset overworld True True", client.Calls);
    }

    [Fact]
    public async Task Tasks_refresh_formats_the_rows()
    {
        var client = new FakeClient();
        client.Tasks.Add(new TaskEntry
        {
            Id = 1, Name = "nightly", Cron = "0 4 * * *", Action = "restart", Enabled = true,
            Warn = new List<int> { 300, 45 }, NextRun = "2026-10-09T04:00:00", LastResult = new TaskLastResult { Ok = false, Code = "task_failed" },
        });
        var vm = new TasksViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        var item = Assert.Single(vm.Items);
        Assert.Equal("5m, 45s", item.WarnText);
        Assert.Equal("2026-10-09 04:00:00", item.NextRun);
        Assert.Equal("task_failed", item.LastResult);
    }

    [Fact]
    public async Task Tasks_create_validates_cron_and_command()
    {
        var client = new FakeClient();
        var errors = new ErrorReporter();
        var vm = new TasksViewModel(client, errors, "survie");

        await vm.CreateAsync();
        Assert.Equal("cron_required", errors.Code);

        vm.NewCron = "0 4 * * *";
        vm.NewAction = "command";
        await vm.CreateAsync();
        Assert.Equal("command_required", errors.Code);
        Assert.Empty(client.Calls);

        vm.NewCommand = "say hi";
        vm.NewName = "greet";
        vm.NewWarn = "5m";
        await vm.CreateAsync();

        Assert.Equal("task-create command 0 4 * * * greet say hi ", client.Calls[0]);
        Assert.Equal("", vm.NewCron);
        Assert.Single(vm.Items);
    }

    [Fact]
    public async Task Tasks_create_sends_warnings_for_a_restart_only()
    {
        var client = new FakeClient();
        var vm = new TasksViewModel(client, new ErrorReporter(), "survie") { NewCron = "0 4 * * *", NewWarn = "5m,1m" };

        await vm.CreateAsync();

        Assert.Equal("task-create restart 0 4 * * *   5m,1m", client.Calls[0]);
    }

    [Fact]
    public async Task Tasks_toggle_delete_and_run()
    {
        var client = new FakeClient();
        client.Tasks.Add(new TaskEntry { Id = 1, Name = "a", Cron = "* * * * *", Action = "backup", Enabled = true });
        client.StartedJobs.Enqueue(Done());
        var vm = new TasksViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };
        await vm.RefreshAsync();

        await vm.SetEnabledAsync(1, false);
        Assert.False(vm.Items[0].Enabled);

        await vm.RunAsync(1);
        Assert.Equal("run", vm.LastDone);

        await vm.DeleteAsync(1, false);
        Assert.Single(vm.Items);
        await vm.DeleteAsync(1, true);
        Assert.Empty(vm.Items);
    }

    [Fact]
    public async Task Settings_never_expose_secret_values()
    {
        var client = new FakeClient();
        client.Config["nom_serveur"] = Json("\"Survie\"");
        client.Config["port"] = Json("25565");
        client.Config["mcrcon_pass"] = Json("\"leaked\"");
        client.Secrets.Add("mcrcon_pass");
        client.JavaRuntimesFound["21"] = "/j/21";
        client.JavaRuntimesFound["17"] = "/j/17";
        client.ServerJava = "21";
        client.Mode = "always-on";
        var vm = new SettingsViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        Assert.Equal("Survie", vm.Items.First(i => i.Key == "nom_serveur").Value);
        Assert.Equal("25565", vm.Items.First(i => i.Key == "port").Value);
        var secret = vm.Items.First(i => i.Key == "mcrcon_pass");
        Assert.True(secret.IsSecret);
        Assert.True(secret.IsSet);
        Assert.Equal("", secret.Value);
        Assert.DoesNotContain(vm.Items, i => i.Value == "leaked" || i.Original == "leaked");
        Assert.Equal("always-on", vm.Mode);
        Assert.Equal(new[] { "system", "17", "21" }, vm.JavaChoices);
        Assert.Equal("21", vm.JavaChoice);
    }

    [Fact]
    public async Task Settings_save_sends_only_changes_and_an_empty_secret_is_unchanged()
    {
        var client = new FakeClient { RestartNeeded = true };
        client.Config["nom_serveur"] = Json("\"Survie\"");
        client.Config["ram_allocation"] = Json("\"4G\"");
        client.Secrets.Add("mcrcon_pass");
        var vm = new SettingsViewModel(client, new ErrorReporter(), "survie");
        await vm.RefreshAsync();
        client.Calls.Clear();

        await vm.SaveAsync();
        Assert.Empty(client.Calls);

        vm.Items.First(i => i.Key == "ram_allocation").Value = " 8G ";
        vm.Items.First(i => i.Key == "mcrcon_pass").Value = "s3cret";
        await vm.SaveAsync();

        Assert.Contains("config-set ram_allocation=8G", client.Calls);
        Assert.Contains("config-set mcrcon_pass=s3cret", client.Calls);
        Assert.DoesNotContain("config-set nom_serveur=Survie", client.Calls);
        Assert.True(vm.RestartRequired);
        Assert.Equal("save", vm.LastDone);
    }

    [Fact]
    public async Task Settings_mode_schedule_and_java()
    {
        var client = new FakeClient();
        client.Config["heure_ouverture"] = Json("20");
        client.Config["minute_ouverture"] = Json("0");
        client.Config["heure_fermeture"] = Json("3");
        client.Config["minute_fermeture"] = Json("30");
        client.JavaRuntimesFound["21"] = "/j/21";
        var errors = new ErrorReporter();
        var vm = new SettingsViewModel(client, errors, "survie");
        await vm.RefreshAsync();
        Assert.Equal("20:00", vm.OpenTime);
        Assert.Equal("03:30", vm.CloseTime);

        await vm.SetModeAsync("maintenance");
        Assert.Equal("maintenance", vm.Mode);
        Assert.Contains("mode maintenance", client.Calls);

        vm.OpenTime = "25:00";
        await vm.SaveScheduleAsync();
        Assert.Equal("invalid_time", errors.Code);
        vm.OpenTime = "21:15";
        await vm.SaveScheduleAsync();
        Assert.Contains("schedule 21:15-3:30", client.Calls);

        vm.JavaChoice = "21";
        await vm.SaveJavaAsync();
        Assert.Contains("java-set 21", client.Calls);
    }

    [Fact]
    public void Clock_parsing_is_strict()
    {
        Assert.True(SettingsViewModel.TryParseClock("07:05", out var h, out var m));
        Assert.Equal((7, 5), (h, m));
        Assert.False(SettingsViewModel.TryParseClock("7", out _, out _));
        Assert.False(SettingsViewModel.TryParseClock("12:60", out _, out _));
        Assert.False(SettingsViewModel.TryParseClock("-1:00", out _, out _));
    }

    [Fact]
    public void Wizard_validates_each_step_before_moving_on()
    {
        var errors = new ErrorReporter();
        var vm = new CreateServerViewModel(new FakeClient(), errors);

        vm.NextCommand.Execute(null);
        Assert.Equal(0, vm.Step);
        Assert.Equal("name_required", errors.Code);

        vm.Name = "creatif";
        vm.NextCommand.Execute(null);
        Assert.Equal(1, vm.Step);

        vm.Ram = "lots";
        vm.NextCommand.Execute(null);
        Assert.Equal(1, vm.Step);
        Assert.Equal("invalid_ram", errors.Code);

        vm.Ram = "6g";
        vm.Port = "80";
        vm.NextCommand.Execute(null);
        Assert.Equal("invalid_port", errors.Code);

        vm.Port = "25570";
        vm.NextCommand.Execute(null);
        Assert.Equal(2, vm.Step);
        Assert.True(vm.IsLastStep);
        Assert.False(vm.CanCreate);

        vm.BackCommand.Execute(null);
        Assert.Equal(1, vm.Step);
    }

    [Fact]
    public async Task Wizard_creates_only_after_the_eula_is_accepted()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(Done());
        var vm = new CreateServerViewModel(client, new ErrorReporter()) { JobPollInterval = TimeSpan.Zero, Name = " creatif ", Loader = "Fabric", Ram = "6g", Port = "25570" };
        vm.NextCommand.Execute(null);
        vm.NextCommand.Execute(null);

        await vm.CreateAsync();
        Assert.Null(client.Created);

        vm.AcceptEula = true;
        Assert.True(vm.CanCreate);
        await vm.CreateAsync();

        Assert.NotNull(client.Created);
        Assert.Equal("creatif", client.Created!.Name);
        Assert.Equal("Fabric", client.Created.Loader);
        Assert.Equal("6G", client.Created.Ram);
        Assert.Equal(25570, client.Created.Port);
        Assert.Null(client.Created.Version);
        Assert.True(client.Created.AcceptEula);
        Assert.Equal("creatif", vm.CreatedName);
    }

    [Fact]
    public async Task Wizard_failure_is_reported_and_keeps_the_form()
    {
        var client = new FakeClient();
        client.StartedJobs.Enqueue(new Job { Id = "j", State = "failed", Result = new JobResult { Code = "folder_not_empty" } });
        var errors = new ErrorReporter();
        var vm = new CreateServerViewModel(client, errors) { JobPollInterval = TimeSpan.Zero, Name = "creatif" };
        vm.NextCommand.Execute(null);
        vm.NextCommand.Execute(null);
        vm.AcceptEula = true;

        await vm.CreateAsync();

        Assert.Equal("folder_not_empty", errors.Code);
        Assert.Equal("", vm.CreatedName);
        Assert.Equal("creatif", vm.Name);
        Assert.False(vm.IsBusy);
    }
}
