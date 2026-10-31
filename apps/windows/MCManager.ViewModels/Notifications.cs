using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record AppNotice(string Kind, string Server, string Detail)
{
    public string Id => Kind + "-" + Server;
}

public sealed partial class NotificationPrefs : ObservableObject
{
    public static readonly IReadOnlyList<string> Kinds = new[] { "crash", "backup_failed", "join" };

    private readonly Action<IReadOnlyDictionary<string, bool>>? _save;
    private bool _loading;

    public NotificationPrefs(IReadOnlyDictionary<string, bool>? saved = null, Action<IReadOnlyDictionary<string, bool>>? save = null)
    {
        _save = save;
        _loading = true;
        Crash = Saved(saved, "crash");
        BackupFailed = Saved(saved, "backup_failed");
        Join = Saved(saved, "join");
        _loading = false;
    }

    [ObservableProperty]
    private bool _crash;

    [ObservableProperty]
    private bool _backupFailed;

    [ObservableProperty]
    private bool _join;

    private static bool Saved(IReadOnlyDictionary<string, bool>? saved, string kind)
        => saved is null || !saved.TryGetValue(kind, out var value) || value;

    partial void OnCrashChanged(bool value) => Persist();

    partial void OnBackupFailedChanged(bool value) => Persist();

    partial void OnJoinChanged(bool value) => Persist();

    private void Persist()
    {
        if (!_loading)
        {
            _save?.Invoke(new Dictionary<string, bool> { ["crash"] = Crash, ["backup_failed"] = BackupFailed, ["join"] = Join });
        }
    }

    public bool IsEnabled(string kind) => kind switch
    {
        "crash" => Crash,
        "backup_failed" => BackupFailed,
        "join" => Join,
        _ => false,
    };

    public AppNotice? NoticeFor(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            return document.RootElement.ValueKind == JsonValueKind.Object ? Map(document.RootElement) : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private AppNotice? Map(JsonElement root)
    {
        var server = Text(root, "server");
        switch (Text(root, "type"))
        {
            case "alert":
                var name = Text(root, "event");
                var pref = name switch
                {
                    "crash" or "crash_loop" => "crash",
                    "backup_failed" => "backup_failed",
                    _ => "",
                };
                return pref.Length > 0 && IsEnabled(pref) ? new AppNotice(name, server, Text(root, "detail")) : null;
            case "players":
                if (!IsEnabled("join") || !root.TryGetProperty("joined", out var joined) || joined.ValueKind != JsonValueKind.Array)
                {
                    return null;
                }
                var names = joined.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString() ?? "").ToList();
                return names.Count == 0 ? null : new AppNotice("join", server, string.Join(", ", names));
            default:
                return null;
        }
    }

    private static string Text(JsonElement root, string name)
        => root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
}

public sealed class EventWatcher
{
    private readonly IMcClient _client;
    private readonly NotificationPrefs _prefs;
    private readonly Action<AppNotice> _deliver;
    private CancellationTokenSource? _cts;

    public EventWatcher(IMcClient client, NotificationPrefs prefs, Action<AppNotice> deliver)
    {
        _client = client;
        _prefs = prefs;
        _deliver = deliver;
    }

    public TimeSpan RetryDelay { get; set; } = TimeSpan.FromSeconds(5);

    public async Task ConsumeAsync(CancellationToken ct)
    {
        try
        {
            await foreach (var item in _client.StreamEventsAsync(ct))
            {
                var notice = _prefs.NoticeFor(item.Data);
                if (notice is not null)
                {
                    _deliver(notice);
                }
            }
        }
        catch (Exception ex) when (ex is ApiException or HttpRequestException or IOException)
        {
        }
    }

    public void Start()
    {
        Stop();
        var cts = new CancellationTokenSource();
        _cts = cts;
        _ = RunAsync(cts.Token);
    }

    private async Task RunAsync(CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await ConsumeAsync(ct);
                await Task.Delay(RetryDelay, ct);
            }
        }
        catch (OperationCanceledException)
        {
        }
    }

    public void Stop()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
    }
}
