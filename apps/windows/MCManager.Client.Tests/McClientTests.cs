using System.Net;
using System.Text;
using System.Text.Json;
using Xunit;

namespace MCManager.Client.Tests;

public class McClientTests
{
    [Fact]
    public async Task ListServers_parses_the_contract_example()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.ServerList);
        var servers = await handler.Client().ListServersAsync();
        var server = Assert.Single(servers);
        Assert.Equal("survie", server.Name);
        Assert.Equal("running", server.State);
        Assert.Equal("always-on", server.Mode);
        Assert.Equal(6291456, server.RssKb);
        Assert.Equal(7312, server.UptimeS);
        Assert.Equal("/v1/servers", handler.Requests[0].Path);
    }

    [Fact]
    public async Task GetServer_encodes_the_name()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Snapshot);
        var server = await handler.Client().GetServerAsync("my server");
        Assert.True(server.Active);
        Assert.Equal("1.21.1", server.Version);
        Assert.Equal("/v1/servers/my%20server", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Start_posts_without_a_body()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Started);
        var result = await handler.Client().StartServerAsync("survie");
        Assert.Equal("started", result.Code);
        Assert.Equal(HttpMethod.Post, handler.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/start", handler.Requests[0].Path);
        Assert.Null(handler.Requests[0].Body);
    }

    [Fact]
    public async Task Stop_sends_snake_case_options_and_omits_nulls()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Stopped);
        var result = await handler.Client().StopServerAsync("survie", new StopRequest { Force = false, Reason = "maintenance" });
        Assert.Equal("stopped", result.Code);
        using var body = JsonDocument.Parse(handler.Requests[0].Body!);
        Assert.False(body.RootElement.GetProperty("force").GetBoolean());
        Assert.Equal("maintenance", body.RootElement.GetProperty("reason").GetString());
        Assert.False(body.RootElement.TryGetProperty("quiet", out _));
    }

    [Fact]
    public async Task Restart_returns_the_accepted_job()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Accepted, Samples.RestartJob);
        var job = await handler.Client().RestartServerAsync("survie");
        Assert.Equal("j_restartserve", job.Id);
        Assert.Equal("running", job.State);
        Assert.False(job.IsFinished);
    }

    [Fact]
    public async Task Resume_parses_the_result()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Resumed);
        var result = await handler.Client().ResumeServerAsync("survie");
        Assert.Equal("resumed", result.Code);
        Assert.Equal("always-on", result.Mode);
    }

    [Fact]
    public async Task Console_command_is_sent_as_json()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.ConsoleReply);
        var reply = await handler.Client().SendConsoleCommandAsync("survie", "list");
        Assert.Contains("Steve, Alex", reply.Output);
        Assert.Equal("""{"command":"list"}""", handler.Requests[0].Body);
        Assert.Equal("/v1/servers/survie/console", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Online_players_are_parsed()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Players);
        var players = await handler.Client().GetOnlinePlayersAsync("survie");
        Assert.Equal(2, players.Online);
        Assert.Equal(20, players.Max);
        Assert.Equal(new[] { "Steve", "Alex" }, players.Players);
    }

    [Fact]
    public async Task Player_list_entries_are_parsed()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Whitelist);
        var listing = await handler.Client().GetPlayerListAsync("survie", "whitelist");
        Assert.True(listing.Enabled);
        Assert.Equal("Notch", Assert.Single(listing.Entries).Subject);
        Assert.Equal("/v1/servers/survie/lists/whitelist", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Add_to_list_sends_subject_and_reason()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.BanAdded);
        var result = await handler.Client().AddPlayerListEntryAsync("survie", "ban", "Notch", "grief");
        Assert.Equal("ban_added", result.Code);
        Assert.True(result.Changed);
        Assert.Equal("""{"subject":"Notch","reason":"grief"}""", handler.Requests[0].Body);
    }

    [Fact]
    public async Task Remove_from_list_uses_delete_and_encodes_the_subject()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.BanRemoved);
        var result = await handler.Client().RemovePlayerListEntryAsync("survie", "banip", "::1");
        Assert.Equal("ban_removed", result.Code);
        Assert.Equal(HttpMethod.Delete, handler.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/lists/banip/%3A%3A1", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Kick_posts_the_player()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Kicked);
        var result = await handler.Client().KickPlayerAsync("survie", "Steve");
        Assert.Equal("kicked", result.Code);
        Assert.Equal("""{"player":"Steve"}""", handler.Requests[0].Body);
    }

    [Fact]
    public async Task Jobs_are_listed_with_a_state_filter()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.Jobs);
        var jobs = await handler.Client().ListJobsAsync("running");
        var job = Assert.Single(jobs);
        Assert.Equal(40, job.Progress);
        Assert.Equal("/v1/jobs?state=running", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Http_error_becomes_an_api_exception()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Unauthorized, Samples.Unauthorized);
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().ListServersAsync());
        Assert.Equal("unauthorized", error.Code);
        Assert.Equal(401, error.Status);
        Assert.Equal("Device token missing or revoked.", error.Message);
    }

    [Fact]
    public async Task Ok_false_with_status_200_is_an_error()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, """{"ok": false, "code": "check_failed", "message": "nope"}""");
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().GetServerAsync("survie"));
        Assert.Equal("check_failed", error.Code);
        Assert.Equal(200, error.Status);
    }

    [Fact]
    public async Task Error_without_message_falls_back_to_the_code()
    {
        var handler = FakeHandler.Json(HttpStatusCode.NotFound, """{"ok": false, "code": "not_found"}""");
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().GetServerAsync("x"));
        Assert.Equal("not_found", error.Message);
        Assert.Equal("", error.DaemonMessage);
    }

    [Fact]
    public async Task Garbage_answer_is_bad_answer()
    {
        var handler = new FakeHandler((_, _) => (HttpStatusCode.InternalServerError, "<html>", "text/html"));
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().ListServersAsync());
        Assert.Equal("bad_answer", error.Code);
        Assert.Equal(500, error.Status);
    }

    [Fact]
    public async Task Unreachable_daemon_is_reported()
    {
        var http = new HttpClient(new ThrowingHandler()) { BaseAddress = new Uri("http://127.0.0.1:1/") };
        var error = await Assert.ThrowsAsync<ApiException>(() => new McClient(http).ListServersAsync());
        Assert.Equal("daemon_unreachable", error.Code);
        Assert.Equal(0, error.Status);
    }

    [Fact]
    public async Task Create_sets_the_bearer_token()
    {
        using var client = McClient.Create(new ApiEndpoint("127.0.0.1", 1, "secret"));
        Assert.NotNull(client);
        var handler = FakeHandler.Json(HttpStatusCode.OK, Samples.ServerList);
        var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:1/") };
        http.DefaultRequestHeaders.Authorization = new("Bearer", "secret");
        await new McClient(http).ListServersAsync();
        Assert.Equal("Bearer secret", handler.Last!.Headers.Authorization!.ToString());
    }

    [Fact]
    public async Task Console_stream_yields_lines_and_skips_comments()
    {
        const string stream = ": ping\n\nid: 7\nevent: line\ndata: [10:00:31] [Server thread/INFO]: Done (8.2s)!\n\nevent: line\ndata: second\n\n";
        var handler = new FakeHandler((_, _) => (HttpStatusCode.OK, stream, "text/event-stream"));
        var events = new List<ConsoleEvent>();
        await foreach (var item in handler.Client().StreamConsoleAsync("survie", 50))
        {
            events.Add(item);
        }
        Assert.Equal(2, events.Count);
        Assert.Equal("line", events[0].Name);
        Assert.Equal("[10:00:31] [Server thread/INFO]: Done (8.2s)!", events[0].Data);
        Assert.Equal("7", events[0].Id);
        Assert.Equal("second", events[1].Data);
        Assert.Equal("/v1/servers/survie/console?tail=50", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Console_stream_failure_throws_an_api_exception()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Conflict, """{"ok": false, "code": "console_offline", "message": "off"}""");
        var error = await Assert.ThrowsAsync<ApiException>(async () =>
        {
            await foreach (var _ in handler.Client().StreamConsoleAsync("survie"))
            {
            }
        });
        Assert.Equal("console_offline", error.Code);
        Assert.Equal(409, error.Status);
    }

    [Fact]
    public async Task Sse_reader_joins_multiline_data()
    {
        var bytes = Encoding.UTF8.GetBytes("data: a\ndata: b\n\n");
        var events = new List<ConsoleEvent>();
        await foreach (var item in SseReader.ReadAsync(new MemoryStream(bytes)))
        {
            events.Add(item);
        }
        var single = Assert.Single(events);
        Assert.Equal("message", single.Name);
        Assert.Equal("a\nb", single.Data);
    }

    private sealed class ThrowingHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => throw new HttpRequestException("refused");
    }
}
