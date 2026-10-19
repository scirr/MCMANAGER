using MCManager.Client;
using Xunit;

namespace MCManager.ViewModels.Tests;

public class ViewModelTests
{
    private static ServerSnapshot Snapshot(string name, string state) => new()
    {
        Name = name, State = state, Loader = "Fabric", Version = "1.21.1", RssKb = 6291456, Active = true,
    };

    [Fact]
    public async Task Server_list_shows_state_players_and_ram()
    {
        var client = new FakeClient();
        client.Servers.Add(Snapshot("survie", "running"));
        client.Servers.Add(Snapshot("creatif", "stopped"));
        client.Online["survie"] = new PlayersOnline { Ok = true, Online = 2, Max = 20 };
        var vm = new ServerListViewModel(client, new ErrorReporter());

        await vm.RefreshAsync();

        Assert.Equal(2, vm.Servers.Count);
        var survie = vm.Servers[0];
        Assert.Equal("running", survie.State);
        Assert.Equal("2/20", survie.PlayersText);
        Assert.Equal("6.0 GB", survie.RamText);
        Assert.Equal("Fabric 1.21.1", survie.Version);
        Assert.Equal("-", vm.Servers[1].PlayersText);
        Assert.DoesNotContain("players creatif", client.Calls);
        Assert.False(vm.IsEmpty);
    }

    [Fact]
    public async Task Server_list_keeps_items_and_drops_removed_servers()
    {
        var client = new FakeClient();
        client.Servers.Add(Snapshot("a", "stopped"));
        client.Servers.Add(Snapshot("b", "stopped"));
        var vm = new ServerListViewModel(client, new ErrorReporter());
        await vm.RefreshAsync();
        var first = vm.Servers[0];

        client.Servers.RemoveAt(1);
        await vm.RefreshAsync();

        Assert.Single(vm.Servers);
        Assert.Same(first, vm.Servers[0]);
    }

    [Fact]
    public async Task Server_list_reports_api_errors()
    {
        var client = new FakeClient { Failure = new ApiException("daemon_unreachable", "no daemon", 0) };
        var errors = new ErrorReporter();
        var vm = new ServerListViewModel(client, errors);

        await vm.RefreshAsync();

        Assert.True(errors.IsOpen);
        Assert.Equal("daemon_unreachable", errors.Code);
        Assert.Equal("no daemon", errors.Message);
        Assert.False(vm.IsLoading);
    }

    [Fact]
    public async Task Server_list_tolerates_a_players_failure()
    {
        var client = new FakeClient { PlayersFailure = new ApiException("rcon_failed", "", 503) };
        client.Servers.Add(Snapshot("survie", "running"));
        var errors = new ErrorReporter();
        var vm = new ServerListViewModel(client, errors);

        await vm.RefreshAsync();

        Assert.False(errors.IsOpen);
        Assert.Equal("-", vm.Servers[0].PlayersText);
    }

    [Theory]
    [InlineData(null, "-")]
    [InlineData(0L, "-")]
    [InlineData(524288L, "512 MB")]
    [InlineData(1572864L, "1.5 GB")]
    public void Ram_is_formatted(long? kb, string expected)
    {
        Assert.Equal(expected, ServerItemViewModel.FormatRam(kb));
    }

    [Fact]
    public async Task Detail_enables_actions_from_the_state()
    {
        var client = new FakeClient { State = "stopped" };
        var vm = new ServerDetailViewModel(client, new ErrorReporter(), "survie");
        await vm.RefreshAsync();
        Assert.True(vm.CanStart);
        Assert.False(vm.CanStop);
        Assert.False(vm.CanRestart);

        client.State = "maintenance";
        await vm.RefreshAsync();
        Assert.True(vm.CanResume);
        Assert.False(vm.CanStart);
    }

    [Fact]
    public async Task Detail_start_calls_the_api_then_refreshes()
    {
        var client = new FakeClient { State = "stopped" };
        var vm = new ServerDetailViewModel(client, new ErrorReporter(), "survie");

        await vm.StartAsync();

        Assert.Equal(new[] { "start survie", "get survie", "players survie" }, client.Calls);
        Assert.Equal("running", vm.State);
        Assert.True(vm.CanStop);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Detail_reports_a_refused_action()
    {
        var client = new FakeClient { Failure = new ApiException("server_running", "already", 409) };
        var errors = new ErrorReporter();
        var vm = new ServerDetailViewModel(client, errors, "survie");

        await vm.StartAsync();

        Assert.Equal("server_running", errors.Code);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Detail_restart_waits_for_the_job()
    {
        var client = new FakeClient();
        client.JobStates.Enqueue(new Job { Id = "j1", State = "running" });
        client.JobStates.Enqueue(new Job { Id = "j1", State = "succeeded" });
        var vm = new ServerDetailViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.RestartAsync();

        Assert.Equal(2, client.Calls.Count(c => c == "job j1"));
    }

    [Fact]
    public async Task Detail_restart_reports_a_failed_job()
    {
        var client = new FakeClient();
        client.JobStates.Enqueue(new Job { Id = "j1", State = "failed", Result = new JobResult { Code = "start_failed", Message = "boom" } });
        var errors = new ErrorReporter();
        var vm = new ServerDetailViewModel(client, errors, "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.RestartAsync();

        Assert.Equal("start_failed", errors.Code);
        Assert.Equal("boom", errors.Message);
    }

    private static BackupEntry Backup(string id) => new()
    {
        Id = id, File = id + ".zip", Type = "midi", Created = "2026-10-08T12:00:03", Size = 1288490188,
    };

    [Fact]
    public async Task Backups_refresh_lists_date_size_and_origin()
    {
        var client = new FakeClient();
        client.Backups.Add(Backup("a_midi"));
        var vm = new BackupsViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        var item = Assert.Single(vm.Items);
        Assert.Equal("2026-10-08 12:00:03", item.Date);
        Assert.Equal("1.2 GB", item.SizeText);
        Assert.Equal("midi", item.Origin);
        Assert.False(vm.IsEmpty);
    }

    [Fact]
    public async Task Backups_create_follows_the_job_progress_then_reloads()
    {
        var client = new FakeClient();
        client.JobStates.Enqueue(new Job { Id = "jb", State = "running", Progress = 40 });
        client.JobStates.Enqueue(new Job { Id = "jb", State = "succeeded", Progress = 100 });
        var vm = new BackupsViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.CreateAsync();

        Assert.Equal(new[] { "create-backup survie", "job jb", "job jb", "backups survie" }, client.Calls);
        Assert.Equal(100, vm.Progress);
        Assert.Equal("create", vm.LastDone);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Backups_restore_needs_the_confirmation()
    {
        var client = new FakeClient();
        client.JobStates.Enqueue(new Job { Id = "jr", State = "succeeded" });
        var vm = new BackupsViewModel(client, new ErrorReporter(), "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.RestoreAsync("a_midi", false);
        Assert.Empty(client.Calls);

        await vm.RestoreAsync("a_midi", true);
        Assert.Equal("restore a_midi True", client.Calls[0]);
        Assert.Equal("restore", vm.LastDone);
    }

    [Fact]
    public async Task Backups_failed_job_is_reported_by_code()
    {
        var client = new FakeClient();
        client.JobStates.Enqueue(new Job { Id = "jr", State = "failed", Result = new JobResult { Code = "stop_first", Message = "stop" } });
        var errors = new ErrorReporter();
        var vm = new BackupsViewModel(client, errors, "survie") { JobPollInterval = TimeSpan.Zero };

        await vm.RestoreAsync("a_midi", true);

        Assert.Equal("stop_first", errors.Code);
        Assert.Equal("", vm.LastDone);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Console_appends_streamed_lines_and_caps_the_buffer()
    {
        var client = new FakeClient();
        for (var i = 0; i < ConsoleViewModel.MaxLines + 5; i++)
        {
            client.Stream.Add(new ConsoleEvent(null, "line", "l" + i));
        }
        client.Stream.Add(new ConsoleEvent(null, "other", "ignored"));
        var vm = new ConsoleViewModel(client, new ErrorReporter(), "survie");

        vm.Start();
        await vm.Completion;

        Assert.Equal(ConsoleViewModel.MaxLines, vm.Lines.Count);
        Assert.Equal("l5", vm.Lines[0]);
        Assert.False(vm.IsStreaming);
    }

    [Fact]
    public async Task Console_stream_error_is_reported()
    {
        var client = new FakeClient { Failure = new ApiException("console_offline", "off", 409) };
        var errors = new ErrorReporter();
        var vm = new ConsoleViewModel(client, errors, "survie");

        vm.Start();
        await vm.Completion;

        Assert.Equal("console_offline", errors.Code);
    }

    [Fact]
    public async Task Console_send_echoes_the_command_and_the_reply()
    {
        var client = new FakeClient();
        var vm = new ConsoleViewModel(client, new ErrorReporter(), "survie") { CommandText = " list " };

        await vm.SendAsync();

        Assert.Equal(new[] { "> list", "line1", "line2" }, vm.Lines);
        Assert.Equal("", vm.CommandText);
        Assert.Contains("console list", client.Calls);
    }

    [Fact]
    public async Task Console_ignores_an_empty_command()
    {
        var client = new FakeClient();
        var vm = new ConsoleViewModel(client, new ErrorReporter(), "survie") { CommandText = "  " };
        await vm.SendAsync();
        Assert.Empty(client.Calls);
    }

    [Fact]
    public async Task Players_load_online_and_list()
    {
        var client = new FakeClient();
        client.Online["survie"] = new PlayersOnline { Ok = true, Online = 1, Max = 20, Players = { "Steve" } };
        client.Lists["whitelist"] = new List<PlayerListEntry> { new() { Name = "Notch" } };
        var vm = new PlayersViewModel(client, new ErrorReporter(), "survie");

        await vm.RefreshAsync();

        Assert.Equal(new[] { "Steve" }, vm.Online);
        Assert.Equal("1/20", vm.OnlineText);
        Assert.Equal("Notch", Assert.Single(vm.Entries).Subject);
    }

    [Fact]
    public async Task Players_offline_server_is_not_an_error()
    {
        var client = new FakeClient { PlayersFailure = new ApiException("server_offline", "off", 409) };
        var errors = new ErrorReporter();
        var vm = new PlayersViewModel(client, errors, "survie");

        await vm.LoadOnlineAsync();

        Assert.False(errors.IsOpen);
        Assert.Equal("-", vm.OnlineText);
    }

    [Fact]
    public async Task Players_add_and_remove_update_the_list()
    {
        var client = new FakeClient();
        var vm = new PlayersViewModel(client, new ErrorReporter(), "survie") { NewSubject = " Alex ", Reason = "" };

        await vm.AddAsync();
        Assert.Equal("Alex", Assert.Single(vm.Entries).Subject);
        Assert.Equal("", vm.NewSubject);
        Assert.Contains("add whitelist Alex", client.Calls);

        await vm.RemoveAsync("Alex");
        Assert.Empty(vm.Entries);
    }

    [Fact]
    public async Task Players_kick_calls_the_api()
    {
        var client = new FakeClient();
        var vm = new PlayersViewModel(client, new ErrorReporter(), "survie");
        await vm.KickAsync("Steve");
        Assert.Contains("kick Steve", client.Calls);
    }

    [Fact]
    public async Task Main_opens_and_closes_the_detail()
    {
        var main = new MainViewModel(new FakeClient(), new ErrorReporter());
        main.OpenServer("survie");
        Assert.Equal("survie", main.Detail?.Name);
        main.CloseDetail();
        Assert.Null(main.Detail);
        await Task.CompletedTask;
    }

    [Fact]
    public void Main_without_client_is_disconnected()
    {
        var main = new MainViewModel(null, new ErrorReporter());
        main.OpenServer("survie");
        Assert.False(main.IsConnected);
        Assert.Null(main.ServerList);
        Assert.Null(main.Detail);
    }

    [Fact]
    public void Error_reporter_falls_back_to_the_code_and_clears()
    {
        var errors = new ErrorReporter();
        errors.Report(new ApiException("not_found", "", 404));
        Assert.Equal("not_found", errors.Message);
        errors.Clear();
        Assert.False(errors.IsOpen);
        Assert.Equal("", errors.Message);
    }
}
