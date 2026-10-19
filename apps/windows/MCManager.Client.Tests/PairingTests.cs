using System.Net;
using Xunit;

namespace MCManager.Client.Tests;

public class PairingTests
{
    private const string Pin = "9F:2A:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:C1";

    private static string Paired(string fingerprint = Pin)
        => "{\"ok\":true,\"code\":\"paired\",\"device_id\":\"d_7f3a\",\"token\":\"mcm_abc\",\"fingerprint\":\"" + fingerprint + "\"}";

    [Fact]
    public async Task Pairing_posts_code_and_name_without_a_token_and_returns_the_profile()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Created, Paired());
        var pin = "";
        var client = new PairingClient(p => { pin = p; return handler; });

        var profile = await client.PairAsync("srv.example", 8765, Pin, "48201937", "PC de Cris");

        Assert.Equal(Pin, pin);
        Assert.Equal("mcm_abc", profile.Token);
        Assert.Equal("d_7f3a", profile.DeviceId);
        Assert.Equal(Pin, profile.Fingerprint);
        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/v1/pair", request.Path);
        Assert.Contains("\"code\":\"48201937\"", request.Body);
        Assert.Contains("\"name\":\"PC de Cris\"", request.Body);
        Assert.Null(handler.Last!.Headers.Authorization);
        Assert.Equal("https://srv.example:8765/", handler.Last.RequestUri!.GetLeftPart(UriPartial.Authority) + "/");
    }

    [Fact]
    public async Task Wrong_code_is_reported()
    {
        var handler = FakeHandler.Json((HttpStatusCode)422, "{\"ok\":false,\"code\":\"bad_pair_code\",\"message\":\"\"}");

        var error = await Assert.ThrowsAsync<ApiException>(
            () => new PairingClient(_ => handler).PairAsync("h", 1, Pin, "00000000", "n"));

        Assert.Equal("bad_pair_code", error.Code);
        Assert.Equal(422, error.Status);
    }

    [Fact]
    public async Task Locked_pairing_is_reported()
    {
        var handler = FakeHandler.Json((HttpStatusCode)429, "{\"ok\":false,\"code\":\"pair_locked\",\"message\":\"\"}");

        var error = await Assert.ThrowsAsync<ApiException>(
            () => new PairingClient(_ => handler).PairAsync("h", 1, Pin, "00000000", "n"));

        Assert.Equal("pair_locked", error.Code);
        Assert.Equal(429, error.Status);
    }

    [Fact]
    public async Task Answer_with_another_fingerprint_is_rejected()
    {
        var other = Pin[..^2] + "C2";
        var handler = FakeHandler.Json(HttpStatusCode.Created, Paired(other));

        var error = await Assert.ThrowsAsync<ApiException>(
            () => new PairingClient(_ => handler).PairAsync("h", 1, Pin, "48201937", "n"));

        Assert.Equal("fingerprint_mismatch", error.Code);
    }

    [Fact]
    public async Task Pairing_without_a_valid_pin_sends_nothing()
    {
        var handler = FakeHandler.Json(HttpStatusCode.Created, Paired());

        var error = await Assert.ThrowsAsync<ApiException>(
            () => new PairingClient(_ => handler).PairAsync("h", 1, "", "48201937", "n"));

        Assert.Equal("fingerprint_missing", error.Code);
        Assert.Empty(handler.Requests);
    }
}
