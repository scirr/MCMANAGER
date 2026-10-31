using System.Net;
using Xunit;

namespace MCManager.Client.Tests;

public class McClientHostTests
{
    private const string JobJson = """
    {"code": null, "created_at": "2026-10-08T10:00:00Z", "id": "j_01", "kind": "x", "progress": 10, "result": null, "server": null, "state": "running", "updated_at": "2026-10-08T10:00:02Z"}
    """;

    private const string RouterJson = """
    {"code": "ok", "config": {"allow": ["10.0.0.0/8"], "bind_host": "0.0.0.0", "default": "survie", "deny": [], "enabled": true, "max_connections": 100, "per_ip": 5, "per_second": 10, "port": 25565, "proxy_in": false, "proxy_out": false, "routes": {"play.example": "survie"}, "trusted_proxies": []}, "ok": true, "pending_restart": ["survie"], "schema": 1}
    """;

    [Fact]
    public async Task Alerts_list_add_test_and_remove()
    {
        var list = FakeHandler.Json(HttpStatusCode.OK, """
        {"channels": [{"chat_id": "42", "events": ["crash", "*"], "legacy": false, "name": "bot", "type": "telegram", "secrets_set": ["token"]}, {"events": [], "legacy": true, "name": "legacy", "topic": "mc", "type": "ntfy"}], "code": "ok", "ok": true, "schema": 1, "server": "survie"}
        """);
        var channels = (await list.Client().ListAlertChannelsAsync("survie")).Channels;
        Assert.Equal(2, channels.Count);
        Assert.Equal("42", channels[0].ChatId);
        Assert.Equal(new[] { "crash", "*" }, channels[0].Events);
        Assert.True(channels[1].Legacy);
        Assert.Equal("/v1/servers/survie/alerts", list.Requests[0].Path);

        var add = FakeHandler.Json(HttpStatusCode.Created, """{"channel": "bot", "code": "alert_added", "events": ["crash"], "ok": true, "schema": 1, "type": "telegram"}""");
        var added = await add.Client().AddAlertChannelAsync("survie", new AlertAddRequest { Type = "telegram", Events = "crash", Token = "t", ChatId = "42" });
        Assert.Equal("bot", added.Channel);
        Assert.Equal(HttpMethod.Post, add.Requests[0].Method);
        Assert.Equal("""{"type":"telegram","events":"crash","token":"t","chat_id":"42"}""", add.Requests[0].Body);

        var test = FakeHandler.Json(HttpStatusCode.OK, """{"checks": [{"channel": "bot", "ok": true}], "code": "ok", "ok": true, "schema": 1}""");
        await test.Client().TestAlertChannelsAsync("survie", "bot");
        Assert.Equal("/v1/servers/survie/alerts/test", test.Requests[0].Path);
        Assert.Equal("""{"channel":"bot"}""", test.Requests[0].Body);

        var remove = FakeHandler.Json(HttpStatusCode.OK, """{"channel": "a b", "code": "alert_removed", "ok": true, "schema": 1}""");
        await remove.Client().RemoveAlertChannelAsync("survie", "a b");
        Assert.Equal(HttpMethod.Delete, remove.Requests[0].Method);
        Assert.Equal("/v1/servers/survie/alerts/a%20b", remove.Requests[0].Path);
    }

    [Fact]
    public async Task Alert_test_failure_is_an_api_error()
    {
        var handler = FakeHandler.Json(HttpStatusCode.BadGateway, """{"code": "alert_test_failed", "message": "x", "ok": false, "failed": "bot"}""");
        var error = await Assert.ThrowsAsync<ApiException>(() => handler.Client().TestAlertChannelsAsync("survie"));
        Assert.Equal("alert_test_failed", error.Code);
    }

    [Fact]
    public async Task Java_install_and_remove()
    {
        var install = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        Assert.Equal("j_01", (await install.Client().InstallJavaAsync(21)).Id);
        Assert.Equal(HttpMethod.Put, install.Requests[0].Method);
        Assert.Equal("/v1/java/21", install.Requests[0].Path);

        var remove = FakeHandler.Json(HttpStatusCode.OK, """{"code": "java_removed", "major": 17, "ok": true, "schema": 1}""");
        var removed = await remove.Client().RemoveJavaAsync(17);
        Assert.True(removed.Ok);
        Assert.Equal(HttpMethod.Delete, remove.Requests[0].Method);
        Assert.Equal("/v1/java/17", remove.Requests[0].Path);
    }

    [Fact]
    public async Task Remote_status_switch_and_pairing_code()
    {
        var status = FakeHandler.Json(HttpStatusCode.OK, """{"bind": "0.0.0.0:8443", "code": "ok", "devices": 2, "enabled": true, "fingerprint": "AB:CD", "ok": true, "schema": 1, "tls": "self-signed"}""");
        var remote = await status.Client().GetRemoteStatusAsync();
        Assert.True(remote.Enabled);
        Assert.Equal("AB:CD", remote.Fingerprint);

        var set = FakeHandler.Json(HttpStatusCode.OK, """{"code": "ok", "enabled": false, "ok": true, "schema": 1}""");
        await set.Client().SetRemoteAccessAsync(false);
        Assert.Equal(HttpMethod.Put, set.Requests[0].Method);
        Assert.Equal("/v1/remote", set.Requests[0].Path);
        Assert.Equal("""{"enabled":false}""", set.Requests[0].Body);

        var code = FakeHandler.Json(HttpStatusCode.Created, """{"code": "ok", "expires_in_s": 300, "ok": true, "pairing_code": "ABCD-1234", "role": "viewer", "schema": 1}""");
        var pairing = await code.Client().CreatePairingCodeAsync("viewer", "tablet");
        Assert.Equal("ABCD-1234", pairing.PairingCode);
        Assert.Equal(300, pairing.ExpiresInS);
        Assert.Equal("/v1/pair/codes", code.Requests[0].Path);
        Assert.Equal("""{"role":"viewer","name":"tablet"}""", code.Requests[0].Body);
    }

    [Fact]
    public async Task Devices_roles_revoke_and_audit()
    {
        var list = FakeHandler.Json(HttpStatusCode.OK, """
        {"code": "ok", "devices": [{"created_at": "2026-10-01T09:00:00", "id": "d1", "last_ip": "1.2.3.4", "last_seen": "2026-10-02T10:00:00", "name": "Phone", "revoked": false, "roles": {"default": "operator", "servers": {"survie": "admin"}}, "servers": ["survie"]}], "ok": true, "schema": 1}
        """);
        var device = Assert.Single((await list.Client().ListDevicesAsync()).Devices);
        Assert.Equal("operator", device.Roles.Default);
        Assert.Equal("admin", device.Roles.Servers!["survie"]);
        Assert.Equal(new[] { "survie" }, device.Servers);

        var roles = FakeHandler.Json(HttpStatusCode.OK, """{"created_at": "x", "id": "d1", "last_seen": null, "name": "Phone", "roles": {"default": "admin"}, "ok": true, "code": "ok"}""");
        var changed = await roles.Client().SetDeviceRoleAsync("d1", "admin");
        Assert.Equal("admin", changed.Roles.Default);
        Assert.Equal(HttpMethod.Put, roles.Requests[0].Method);
        Assert.Equal("/v1/devices/d1/roles", roles.Requests[0].Path);
        Assert.Equal("""{"roles":{"default":"admin"}}""", roles.Requests[0].Body);

        var revoke = FakeHandler.Json(HttpStatusCode.OK, """{"code": "ok", "id": "d1", "ok": true, "schema": 1}""");
        await revoke.Client().RevokeDeviceAsync("d1");
        Assert.Equal(HttpMethod.Delete, revoke.Requests[0].Method);
        Assert.Equal("/v1/devices/d1", revoke.Requests[0].Path);

        var audit = FakeHandler.Json(HttpStatusCode.OK, """{"code": "ok", "entries": [{"action": "stop", "at": "2026-10-02T10:00:00", "device": "Phone", "ip": "1.2.3.4", "ok": false, "result": "forbidden", "server": "survie", "status": 403}], "ok": true, "schema": 1}""");
        var entry = Assert.Single((await audit.Client().ListAuditLogAsync(20)).Entries);
        Assert.Equal("stop", entry.Action);
        Assert.False(entry.Ok);
        Assert.Equal("/v1/audit?limit=20", audit.Requests[0].Path);
    }

    [Fact]
    public async Task Update_check_apply_and_rollback()
    {
        var check = FakeHandler.Json(HttpStatusCode.OK, """{"code": "ok", "current": "3.0.0", "latest": "3.1.0", "ok": true, "rollback_available": true, "schema": 1, "signed": true, "update_available": true}""");
        var info = await check.Client().CheckUpdateAsync();
        Assert.True(info.UpdateAvailable);
        Assert.True(info.RollbackAvailable);
        Assert.Equal("3.1.0", info.Latest);

        var apply = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await apply.Client().ApplyUpdateAsync();
        Assert.Equal(HttpMethod.Post, apply.Requests[0].Method);
        Assert.Equal("/v1/update", apply.Requests[0].Path);
        Assert.Equal("{}", apply.Requests[0].Body);

        var rollback = FakeHandler.Json(HttpStatusCode.OK, """{"code": "ok", "ok": true, "previous": "3.0.0", "restarted": true, "schema": 1, "version": "3.0.0"}""");
        await rollback.Client().RollbackUpdateAsync();
        Assert.Equal("/v1/update/rollback", rollback.Requests[0].Path);
    }

    [Fact]
    public async Task Doctor_report_lists_the_checks()
    {
        var handler = FakeHandler.Json(HttpStatusCode.OK, """
        {"checks": [{"detail": "17", "fix": null, "level": "ok", "name": "java", "ok": true, "server": null}, {"detail": "taken", "fix": "change it", "level": "err", "name": "port", "ok": false, "server": "survie"}], "code": "ok", "errors": 1, "has_issues": true, "ok": true, "schema": 1, "warnings": 0}
        """);
        var report = await handler.Client().GetDoctorReportAsync();
        Assert.Equal(1, report.Errors);
        Assert.Equal(2, report.Checks.Count);
        Assert.Null(report.Checks[0].Fix);
        Assert.Equal("survie", report.Checks[1].Server);
        Assert.Equal("/v1/doctor", handler.Requests[0].Path);
    }

    [Fact]
    public async Task Router_reads_and_changes()
    {
        var get = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        var router = await get.Client().GetRouterAsync();
        Assert.True(router.Config.Enabled);
        Assert.Equal("survie", router.Config.Routes["play.example"]);
        Assert.Equal("survie", router.Config.Default);
        Assert.Equal(new[] { "survie" }, router.PendingRestart);

        var enable = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        await enable.Client().SetRouterEnabledAsync(true);
        Assert.Equal("/v1/router/enable", enable.Requests[0].Path);
        Assert.Equal("{}", enable.Requests[0].Body);
        var disable = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        await disable.Client().SetRouterEnabledAsync(false);
        Assert.Equal("/v1/router/disable", disable.Requests[0].Path);

        var route = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        await route.Client().SetRouterRouteAsync("play.example", "survie");
        Assert.Equal(HttpMethod.Put, route.Requests[0].Method);
        Assert.Equal("/v1/router/routes/play.example", route.Requests[0].Path);
        Assert.Equal("""{"server":"survie"}""", route.Requests[0].Body);

        var remove = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        await remove.Client().RemoveRouterRouteAsync("play.example");
        Assert.Equal(HttpMethod.Delete, remove.Requests[0].Method);

        var def = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        await def.Client().SetRouterDefaultAsync("survie");
        Assert.Equal("/v1/router/default", def.Requests[0].Path);

        var access = FakeHandler.Json(HttpStatusCode.OK, RouterJson);
        await access.Client().EditRouterAccessAsync("deny", "add", "1.2.3.0/24");
        Assert.Equal("/v1/router/access", access.Requests[0].Path);
        Assert.Equal("""{"list":"deny","action":"add","cidr":"1.2.3.0/24"}""", access.Requests[0].Body);
    }

    [Fact]
    public async Task Modpack_info_install_and_update()
    {
        var info = FakeHandler.Json(HttpStatusCode.OK, """{"code": "ok", "loader": "neoforge", "loader_version": "21.1", "mc_version": "1.21.1", "ok": true, "schema": 1, "server_files": 1, "source": "atm", "title": "ATM", "version": "1.2"}""");
        var found = await info.Client().GetModpackInfoAsync("all the mods");
        Assert.Equal("ATM", found.Title);
        Assert.Equal("1.21.1", found.McVersion);
        Assert.Equal("/v1/modpacks/info?source=all%20the%20mods", info.Requests[0].Path);

        var install = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await install.Client().InstallModpackAsync(new ModpackInstallRequest { Source = "atm", AcceptEula = true, Ram = "6G", Port = 25570 });
        Assert.Equal("/v1/modpacks", install.Requests[0].Path);
        Assert.Equal("""{"source":"atm","accept_eula":true,"ram":"6G","port":25570}""", install.Requests[0].Body);

        var update = FakeHandler.Json(HttpStatusCode.Accepted, JobJson);
        await update.Client().UpdateModpackAsync("survie");
        Assert.Equal("/v1/servers/survie/modpack/update", update.Requests[0].Path);
        Assert.Equal("{}", update.Requests[0].Body);
    }

    [Fact]
    public async Task Events_stream_yields_the_messages()
    {
        var text = "event: message\ndata: {\"type\":\"alert\"}\n\n";
        var handler = new FakeHandler((_, _) => (HttpStatusCode.OK, text, "text/event-stream"));
        var seen = new List<ConsoleEvent>();
        await foreach (var item in handler.Client().StreamEventsAsync())
        {
            seen.Add(item);
        }
        Assert.Equal("""{"type":"alert"}""", Assert.Single(seen).Data);
        Assert.Equal("/v1/events", handler.Requests[0].Path);
    }
}
