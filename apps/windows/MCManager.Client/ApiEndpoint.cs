using System.Text.Json;

namespace MCManager.Client;

public sealed record ApiEndpoint(string Host, int Port, string Token)
{
    public Uri BaseAddress => new($"http://{Host}:{Port}/");
}

public static class ApiLocator
{
    public const string TokenFileName = "api.token";

    public static IReadOnlyList<string> RunFolders(Func<string, string?> env, string baseDirectory)
    {
        var folders = new List<string>();
        void Add(string? root, params string[] parts)
        {
            if (string.IsNullOrWhiteSpace(root))
            {
                return;
            }
            folders.Add(Path.Combine(new[] { root }.Concat(parts).ToArray()));
        }

        var explicitRun = env("MCMANAGER_RUN_DIR");
        if (!string.IsNullOrWhiteSpace(explicitRun))
        {
            folders.Add(explicitRun);
        }
        Add(baseDirectory, "run");
        Add(baseDirectory, "..", "run");
        Add(baseDirectory, "..", "core", "run");
        Add(baseDirectory, "core", "run");
        Add(env("LOCALAPPDATA"), "MCManager", "run");
        Add(env("APPDATA"), "MCManager", "run");
        Add(env("ProgramFiles"), "MCManager", "run");
        Add(env("ProgramFiles(x86)"), "MCManager", "run");
        Add(env("USERPROFILE"), "MCManager", "run");
        return folders;
    }

    public static ApiEndpoint? Discover()
        => Discover(RunFolders(Environment.GetEnvironmentVariable, AppContext.BaseDirectory));

    public static ApiEndpoint? Discover(IEnumerable<string> runFolders)
    {
        foreach (var folder in runFolders)
        {
            var endpoint = Read(Path.Combine(folder, TokenFileName));
            if (endpoint is not null)
            {
                return endpoint;
            }
        }
        return null;
    }

    public static ApiEndpoint? Read(string tokenPath)
    {
        try
        {
            if (!File.Exists(tokenPath))
            {
                return null;
            }
            var text = File.ReadAllText(tokenPath).TrimStart('﻿');
            var file = JsonSerializer.Deserialize(text, McJson.Default.TokenFile);
            if (file is null || file.Port <= 0 || string.IsNullOrEmpty(file.Token))
            {
                return null;
            }
            return new ApiEndpoint("127.0.0.1", file.Port, file.Token);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }
}
