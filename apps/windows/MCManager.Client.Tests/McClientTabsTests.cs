using System.Net;
using System.Text.Json;
using Xunit;

namespace MCManager.Client.Tests;

public class McClientTabsTests
{
    private const string TaskJson = """
    {"action": "restart", "cron": "0 4 * * *", "enabled": true, "id": 1, "last_result": {"code": "task_restart_done", "ok": true}, "last_run": "2026-10-08T04:00:00", "last_run_ts": 1791374400, "name": "restart-1", "next_run": "2026-10-09T04:00:00", "next_run_ts": 1791460800, "warn": [300, 60]}
    """;

    private const string JobJson = """
    {"code": null, "created_at": "2026-10-08T10:00:00Z", "id": "j_01", "kind": "x", "progress": 10, "result": null, "server": null, "state": "running", "updated_at": "2026-10-08T10:00:02Z"}
    """;

    [Fact]
    public async Task ListMods_parses_the_contract_example()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "ok", "modpack_dir": null, "mods": [{"adds_blocks": true, "file": "lithium-0.13.0.jar", "id": "lithium", "loader": "fabric", "modpack": false, "name": "Lithium", "project": "lithium", "server": true, "source": "modrinth", "version": "0.13.0"}], "mods_dir": "/m", "ok": true, "schema": 1, "server": "survie"}
        """);
        var mods = await handler.Client().ListModsAsync("survie");
        var mod = Assert.Single(mods);
        Assert.Equal("lithium-0.13.0.jar", mod.File);
        Assert.True(mod.AddsBlocks);
        Assert.Equal("modrinth", mod.Source);
        Assert.Equal("/v1/servers/survie/mods", handler.Requests[0].Path);
    }

    [Fact]
    public async Task AddMod_posts_the_reference_and_omits_a_null_source()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        var job = await handler.Client().AddModAsync("survie", "lithium");
        Assert.Equal("j_01", job.Id);
        Assert.Equal(HttpMethod.Post, handler.Requests[0].Method);
        Assert.Equal("""{"ref":"lithium"}""", handler.Requests[0].Body);
    }

    [Fact]
    public async Task RemoveMod_encodes_the_file_and_the_block_confirmation()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "removed", "file": "a b.jar", "moved": ["x"], "ok": true, "restart_required": true, "schema": 1, "server": "survie"}
        """);
        var removed = await handler.Client().RemoveModAsync("survie", "a b.jar", true);
        Assert.True(removed.RestartRequired);
        Assert.Equal(HttpMethod.Delete, handler.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/mods/a%20b.jar?confirm_blocks=true", handler.Requests[0].Path);
    }

    [Fact]
    public async Task RemoveMod_blocks_refusal_is_an_api_error()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Conflict, """{"code": "defines_blocks", "message": "blocks", "ok": false}""");
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().RemoveModAsync("survie", "a.jar"));
        Assert.Equal("defines_blocks", error.Code);
        Assert.Equal(409, error.Status);
    }

    [Fact]
    public async Task UpdateMods_posts_the_name()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await handler.Client().UpdateModsAsync("survie", "lithium");
        Assert.Equal("/v1/servers/survie/mods/update", handler.Requests[0].Path);
        Assert.Equal("""{"name":"lithium"}""", handler.Requests[0].Body);
    }

    [Fact]
    public async Task Datapacks_list_and_toggle()
    {
        var list = FakeHandler.Json(HttpStatusCode.OK, """
        {"builtin": ["vanilla"], "code": "ok", "enabled_order": ["vanilla"], "folder": "/d", "ok": true, "packs": [{"enabled": true, "file": "veinminer.zip", "id": "file/veinminer.zip", "order": 1, "problem": null, "worldgen": false}, {"enabled": null, "file": "bad.zip", "id": "file/bad.zip", "order": null, "problem": "nested", "worldgen": true}], "running": true, "schema": 1, "server": "survie"}
        """);
        var packs = await list.Client().ListDatapacksAsync("survie");
        Assert.True(packs.Running);
        Assert.Equal(2, packs.Packs.Count);
        Assert.True(packs.Packs[0].Enabled);
        Assert.Null(packs.Packs[1].Enabled);
        Assert.Equal("nested", packs.Packs[1].Problem);

        var toggle = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "enabled", "ok": true, "pack": "veinminer.zip", "reply": "Enabled", "restart_required": false, "schema": 1, "server": "survie"}
        """);
        var set = await toggle.Client().SetDatapackEnabledAsync("survie", "veinminer.zip", true);
        Assert.Equal("veinminer.zip", set.Pack);
        Assert.Equal(HttpMethod.Put, toggle.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/datapacks/veinminer.zip", toggle.Requests[0].Path);
        Assert.Equal("""{"enabled":true}""", toggle.Requests[0].Body);
    }

    [Fact]
    public async Task Datapack_placement_is_sent_only_when_enabling()
    {
        var first = FakeHandler.Json(HttpStatusCode.OK, """{"code": "enabled", "ok": true, "pack": "a.zip", "restart_required": false, "schema": 1}""");
        await first.Client().SetDatapackEnabledAsync("survie", "a.zip", true, "first");
        Assert.Equal("""{"enabled":true,"first":true}""", first.Requests[0].Body);

        var vanilla = FakeHandler.Json(HttpStatusCode.OK, """{"code": "enabled", "ok": true, "pack": "a.zip", "restart_required": false, "schema": 1}""");
        await vanilla.Client().SetDatapackEnabledAsync("survie", "a.zip", true, "before_vanilla");
        Assert.Equal("""{"enabled":true,"before_vanilla":true}""", vanilla.Requests[0].Body);

        var off = FakeHandler.Json(HttpStatusCode.OK, """{"code": "disabled", "ok": true, "pack": "a.zip", "restart_required": false, "schema": 1}""");
        await off.Client().SetDatapackEnabledAsync("survie", "a.zip", false, "last");
        Assert.Equal("""{"enabled":false}""", off.Requests[0].Body);
    }

    [Fact]
    public async Task Sleep_settings_read_and_write()
    {
        var get = FakeHandler.Json(HttpStatusCode.OK, """
        {"after_s": 7200, "allow": ["Steve"], "code": "sleep_status", "enabled": true, "freeze": false, "hold_timeout_s": 120, "internal_port": null, "join_mode": "kick", "ok": true, "proxy_protocol": null, "schema": 1, "server": "survie", "state": "running"}
        """);
        var sleep = await get.Client().GetSleepSettingsAsync("survie");
        Assert.True(sleep.Enabled);
        Assert.Equal(7200, sleep.AfterS);
        Assert.Equal("kick", sleep.JoinMode);
        Assert.Equal(120, sleep.HoldTimeoutS);
        Assert.Equal("/v1/servers/survie/sleep", get.Requests[0].Path);

        var put = FakeHandler.Json(HttpStatusCode.OK, """
        {"after_s": 3600, "allow": [], "code": "sleep_updated", "enabled": true, "freeze": true, "hold_timeout_s": 120, "join_mode": "hold", "notes": ["Restart the server to apply the hold mode."], "ok": true, "schema": 1, "server": "survie"}
        """);
        var saved = await put.Client().SetSleepSettingsAsync("survie", new SleepSettingsRequest { Enabled = true, AfterS = 3600, JoinMode = "hold", Freeze = true });
        Assert.True(saved.Freeze);
        Assert.Single(saved.Notes);
        Assert.Equal(HttpMethod.Put, put.Requests[0].Method);
        Assert.Equal("""{"enabled":true,"after_s":3600,"join_mode":"hold","freeze":true}""", put.Requests[0].Body);
    }

    [Fact]
    public async Task Worlds_and_pregen()
    {
        var worlds = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "world_list", "dimensions": [{"id": "overworld", "paths": ["/w"], "size_bytes": 1610612736}], "level": "world", "ok": true, "schema": 1, "server": "survie", "size_bytes": 2147483648}
        """);
        var list = await worlds.Client().ListWorldsAsync("survie");
        Assert.Equal(2147483648, list.SizeBytes);
        Assert.Equal("overworld", Assert.Single(list.Dimensions).Id);

        var status = FakeHandler.Json(HttpStatusCode.OK, """{"code": "pregen_progress", "ok": true, "progress": "11.2%", "schema": 1, "server": "survie"}""");
        Assert.Equal("11.2%", (await status.Client().GetPregenStatusAsync("survie")).Progress);
        Assert.Equal("/v1/servers/survie/worlds/pregen", status.Requests[0].Path);

        var start = FakeHandler.Json(HttpStatusCode.OK, """{"center": [0, 0], "code": "pregen_started", "ok": true, "progress": "Task running.", "radius": 3000, "schema": 1, "server": "survie"}""");
        var started = await start.Client().StartPregenAsync("survie", 3000, "0,0");
        Assert.Equal(3000, started.Radius);
        Assert.Equal("""{"radius":3000,"center":"0,0"}""", start.Requests[0].Body);
    }

    [Fact]
    public async Task ResetDimension_sends_the_confirmation()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await handler.Client().ResetDimensionAsync("survie", "nether", true, false);
        Assert.Equal("/v1/servers/survie/worlds/nether/reset", handler.Requests[0].Path);
        Assert.Equal("""{"confirmed":true}""", handler.Requests[0].Body);

        var overworld = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await overworld.Client().ResetDimensionAsync("survie", "overworld", true, true);
        Assert.Equal("""{"confirmed":true,"include_overworld":true}""", overworld.Requests[0].Body);
    }

    [Fact]
    public async Task Tasks_crud()
    {
        var list = FakeHandler.Json(HttpStatusCode.OK, "{\"code\": \"task_list\", \"ok\": true, \"server\": \"survie\", \"tasks\": [" + TaskJson + "]}");
        var task = Assert.Single(await list.Client().ListTasksAsync("survie"));
        Assert.Equal(1, task.Id);
        Assert.Equal(new[] { 300, 60 }, task.Warn);
        Assert.True(task.LastResult!.Ok);
        Assert.Equal("2026-10-09T04:00:00", task.NextRun);

        var created = FakeHandler.Json(HttpStatusCode.Created, "{\"code\": \"task_added\", \"ok\": true, \"task\": " + TaskJson + "}");
        var result = await created.Client().CreateTaskAsync("survie", new TaskCreateRequest { Cron = "0 4 * * *", Action = "restart", Warn = "5m,1m" });
        Assert.Equal(1, result.Task!.Id);
        Assert.Equal("""{"cron":"0 4 * * *","action":"restart","warn":"5m,1m"}""", created.Requests[0].Body);

        var patch = FakeHandler.Json(HttpStatusCode.OK, "{\"code\": \"task_disabled\", \"ok\": true, \"task\": " + TaskJson + "}");
        await patch.Client().UpdateTaskAsync("survie", 3, false);
        Assert.Equal(HttpMethod.Patch, patch.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/tasks/3", patch.Requests[0].Path);
        Assert.Equal("""{"enabled":false}""", patch.Requests[0].Body);

        var delete = FakeHandler.Json(HttpStatusCode.OK, "{\"code\": \"task_removed\", \"ok\": true, \"task\": " + TaskJson + "}");
        await delete.Client().DeleteTaskAsync("survie", 3);
        Assert.Equal(HttpMethod.Delete, delete.Requests[0].Method);

        var run = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await run.Client().RunTaskAsync("survie", 3, true);
        Assert.Equal("/v1/servers/survie/tasks/3/run", run.Requests[0].Path);
        Assert.Equal("""{"skip_warn":true}""", run.Requests[0].Body);
    }

    [Fact]
    public async Task Config_is_read_and_written_as_text()
    {
        var get = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "config", "config": {"always_on": 1, "nom_serveur": "Survie", "port": 25565, "ram_allocation": "6G"}, "ok": true, "schema": 1, "secrets_set": ["mcrcon_pass"], "server": "survie"}
        """);
        var document = await get.Client().GetServerConfigAsync("survie");
        Assert.Equal(25565, document.Config["port"].GetInt32());
        Assert.Equal("Survie", document.Config["nom_serveur"].GetString());
        Assert.Equal(new[] { "mcrcon_pass" }, document.SecretsSet);

        var set = FakeHandler.Json(HttpStatusCode.OK, """{"code": "config_set", "key": "ram_allocation", "ok": true, "restart_required": true, "schema": 1, "server": "survie", "updated": ["config.json"]}""");
        var result = await set.Client().SetConfigValueAsync("survie", "ram_allocation", "8G");
        Assert.True(result.RestartRequired);
        Assert.Equal(HttpMethod.Put, set.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/config/ram_allocation", set.Requests[0].Path);
        Assert.Equal("""{"value":"8G"}""", set.Requests[0].Body);
    }

    [Fact]
    public async Task Mode_and_schedule()
    {
        var mode = FakeHandler.Json(HttpStatusCode.OK, """{"code": "mode_set", "mode": "schedule", "ok": true, "server": "survie"}""");
        var result = await mode.Client().SetServerModeAsync("survie", "schedule");
        Assert.Equal("schedule", result.Mode);
        Assert.Equal("""{"mode":"schedule"}""", mode.Requests[0].Body);

        var schedule = FakeHandler.Json(HttpStatusCode.OK, """{"close": "03:00", "code": "schedule_updated", "ok": true, "open": "20:00", "server": "survie"}""");
        await schedule.Client().SetServerScheduleAsync("survie", new ScheduleRequest { OpenHour = 20, OpenMinute = 0, CloseHour = 3, CloseMinute = 0 });
        Assert.Equal("/v1/servers/survie/schedule", schedule.Requests[0].Path);
        Assert.Equal("""{"open_hour":20,"open_minute":0,"close_hour":3,"close_minute":0}""", schedule.Requests[0].Body);
    }

    [Fact]
    public async Task Java_accepts_a_number_or_text_for_each_server()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "java_list", "ok": true, "runtimes": {"21": "/j/21"}, "servers": [{"java": 21, "minecraft": "1.21.1", "server": "survie"}, {"java": "system", "minecraft": null, "server": "autre"}]}
        """);
        var java = await handler.Client().ListServerJavaAsync("survie");
        Assert.Equal("/j/21", java.Runtimes["21"]);
        Assert.Equal("21", java.Servers[0].JavaText);
        Assert.Equal("system", java.Servers[1].JavaText);
        Assert.Equal("/v1/servers/survie/java", handler.Requests[0].Path);

        var all = FakeHandler.Json(HttpStatusCode.OK, """{"code": "java_list", "ok": true, "runtimes": {}, "servers": []}""");
        await all.Client().ListJavaAsync();
        Assert.Equal("/v1/java", all.Requests[0].Path);

        var use = FakeHandler.Json(HttpStatusCode.OK, """{"code": "java_use_major", "major": 21, "ok": true, "restart_required": true, "server": "survie"}""");
        var used = await use.Client().SetServerJavaAsync("survie", "21");
        Assert.True(used.RestartRequired);
        Assert.Equal("""{"choice":"21"}""", use.Requests[0].Body);
    }

    [Fact]
    public async Task CreateServer_posts_the_request_and_returns_the_job()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        var job = await handler.Client().CreateServerAsync(new CreateServerRequest { Name = "creatif", Loader = "Paper", AcceptEula = true, Ram = "4G" });
        Assert.Equal("j_01", job.Id);
        Assert.Equal("/v1/servers", handler.Requests[0].Path);
        using var body = JsonDocument.Parse(handler.Requests[0].Body!);
        Assert.True(body.RootElement.GetProperty("accept_eula").GetBoolean());
        Assert.Equal("Paper", body.RootElement.GetProperty("loader").GetString());
        Assert.False(body.RootElement.TryGetProperty("version", out _));
    }

    [Fact]
    public async Task Forbidden_is_an_api_error_with_the_status()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Forbidden, """{"code": "forbidden", "message": "Not allowed for this device.", "ok": false}""");
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().DeleteTaskAsync("survie", 1));
        Assert.Equal("forbidden", error.Code);
        Assert.Equal(403, error.Status);
    }
}
