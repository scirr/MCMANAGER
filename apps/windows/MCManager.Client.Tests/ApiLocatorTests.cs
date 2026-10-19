using Xunit;

namespace MCManager.Client.Tests;

public sealed class ApiLocatorTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "mcm-" + Guid.NewGuid().ToString("N"));

    public ApiLocatorTests()
    {
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        Directory.Delete(_root, true);
    }

    private string Run(string name, string? content)
    {
        var folder = Path.Combine(_root, name, "run");
        Directory.CreateDirectory(folder);
        if (content is not null)
        {
            File.WriteAllText(Path.Combine(folder, "api.token"), content);
        }
        return folder;
    }

    [Fact]
    public void Reads_port_and_token()
    {
        var folder = Run("a", """{"port": 41234, "token": "abc"}""");
        var endpoint = ApiLocator.Discover(new[] { folder });
        Assert.NotNull(endpoint);
        Assert.Equal("127.0.0.1", endpoint!.Host);
        Assert.Equal(41234, endpoint.Port);
        Assert.Equal("abc", endpoint.Token);
        Assert.Equal(new Uri("http://127.0.0.1:41234/"), endpoint.BaseAddress);
    }

    [Fact]
    public void Tolerates_a_byte_order_mark()
    {
        var folder = Run("bom", "﻿{\"port\": 5, \"token\": \"t\"}");
        Assert.Equal(5, ApiLocator.Discover(new[] { folder })!.Port);
    }

    [Fact]
    public void Skips_missing_and_broken_files()
    {
        var missing = Run("missing", null);
        var broken = Run("broken", "{nope");
        var empty = Run("empty", """{"port": 0, "token": ""}""");
        var good = Run("good", """{"port": 9, "token": "z"}""");
        Assert.Equal(9, ApiLocator.Discover(new[] { missing, broken, empty, good })!.Port);
    }

    [Fact]
    public void Returns_null_when_nothing_is_found()
    {
        Assert.Null(ApiLocator.Discover(new[] { Run("none", null) }));
    }

    [Fact]
    public void Explicit_run_folder_comes_first()
    {
        var env = new Dictionary<string, string> { ["MCMANAGER_RUN_DIR"] = "X", ["LOCALAPPDATA"] = "L", ["APPDATA"] = "A" };
        var folders = ApiLocator.RunFolders(key => env.GetValueOrDefault(key), "B");
        Assert.Equal("X", folders[0]);
        Assert.Contains(Path.Combine("B", "run"), folders);
        Assert.Contains(Path.Combine("L", "MCManager", "run"), folders);
        Assert.Contains(Path.Combine("A", "MCManager", "run"), folders);
    }
}
