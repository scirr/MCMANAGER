using System.Text;
using Xunit;

namespace MCManager.Client.Tests;

public sealed class ProfileStoreTests : IDisposable
{
    private const string Token = "mcm_secret_token_value";
    private readonly string _folder = Path.Combine(Path.GetTempPath(), "mcm-" + Guid.NewGuid().ToString("N"));

    private ProfileStore Store() => new(Path.Combine(_folder, "remotes.dat"), new TestProtector());

    private static RemoteProfile Sample(string name = "vps") => new()
    {
        Name = name, Host = "srv.example", Port = 8765, Token = Token, DeviceId = "d_1",
        Fingerprint = "9F:2A:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:C1",
    };

    public void Dispose()
    {
        if (Directory.Exists(_folder))
        {
            Directory.Delete(_folder, true);
        }
    }

    [Fact]
    public void Profiles_survive_a_round_trip_and_the_file_is_not_clear_text()
    {
        var store = Store();
        store.Add(Sample("a"));
        store.Add(Sample("b"));
        store.Add(Sample("a") with { Port = 9000 });

        var loaded = store.Load();

        Assert.Equal(new[] { "b", "a" }, loaded.Select(p => p.Name));
        Assert.Equal(9000, loaded[1].Port);
        Assert.Equal(Token, loaded[0].Token);
        var raw = File.ReadAllBytes(Path.Combine(_folder, "remotes.dat"));
        Assert.DoesNotContain(Token, Encoding.UTF8.GetString(raw));
        Assert.DoesNotContain("srv.example", Encoding.UTF8.GetString(raw));
    }

    [Fact]
    public void Remove_and_corrupt_file()
    {
        var store = Store();
        store.Add(Sample("a"));
        store.Remove("a");
        Assert.Empty(store.Load());

        File.WriteAllBytes(Path.Combine(_folder, "remotes.dat"), new byte[] { 1, 2, 3 });
        Assert.Empty(store.Load());
    }

    [Fact]
    public void Token_is_absent_from_exports_and_text_forms()
    {
        var store = Store();
        store.Add(Sample());
        var profile = store.Load()[0];

        Assert.DoesNotContain(Token, store.Export());
        Assert.DoesNotContain(Token, profile.ToString());
        Assert.DoesNotContain(Token, profile.Summary().ToString());
        Assert.Contains("srv.example", store.Export());
    }
}
