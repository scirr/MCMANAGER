using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;

namespace MCManager.Client;

public sealed class McClient : IMcClient, IDisposable
{
    private readonly HttpClient _http;
    private readonly bool _ownsHttp;

    public McClient(HttpClient http, bool ownsHttp = false)
    {
        _http = http;
        _ownsHttp = ownsHttp;
    }

    public TimeSpan RequestTimeout { get; set; } = TimeSpan.FromSeconds(20);

    public static McClient Create(ApiEndpoint endpoint)
    {
        var http = new HttpClient { BaseAddress = endpoint.BaseAddress, Timeout = Timeout.InfiniteTimeSpan };
        http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", endpoint.Token);
        return new McClient(http, true);
    }

    public void Dispose()
    {
        if (_ownsHttp)
        {
            _http.Dispose();
        }
    }

    private static string Ref(string value) => Uri.EscapeDataString(value);

    private static string ServerPath(string server) => "/v1/servers/" + Ref(server);

    public async Task<IReadOnlyList<ServerSnapshot>> ListServersAsync(CancellationToken ct = default)
        => (await SendAsync(HttpMethod.Get, "/v1/servers", null, McJson.Default.ServerList, ct)).Servers;

    public Task<ServerSnapshot> GetServerAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server), null, McJson.Default.ServerSnapshot, ct);

    public Task<OperationResult> StartServerAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/start", null, McJson.Default.OperationResult, ct);

    public Task<OperationResult> StopServerAsync(string server, StopRequest? request = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/stop", request, McJson.Default.OperationResult, ct);

    public Task<Job> RestartServerAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/restart", null, McJson.Default.Job, ct);

    public Task<OperationResult> ResumeServerAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/resume", null, McJson.Default.OperationResult, ct);

    public Task<OperationResult> SendConsoleCommandAsync(string server, string command, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/console", new ConsoleCommand { Command = command }, McJson.Default.OperationResult, ct);

    public Task<PlayersOnline> GetOnlinePlayersAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/players", null, McJson.Default.PlayersOnline, ct);

    public Task<PlayerListing> GetPlayerListAsync(string server, string kind, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/lists/" + Ref(kind), null, McJson.Default.PlayerListing, ct);

    public Task<OperationResult> AddPlayerListEntryAsync(string server, string kind, string subject, string? reason = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/lists/" + Ref(kind),
            new PlayerListAdd { Subject = subject, Reason = reason }, McJson.Default.OperationResult, ct);

    public Task<OperationResult> RemovePlayerListEntryAsync(string server, string kind, string subject, CancellationToken ct = default)
        => SendAsync(HttpMethod.Delete, ServerPath(server) + "/lists/" + Ref(kind) + "/" + Ref(subject), null, McJson.Default.OperationResult, ct);

    public Task<OperationResult> KickPlayerAsync(string server, string player, string? reason = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/kick",
            new KickRequest { Player = player, Reason = reason }, McJson.Default.OperationResult, ct);

    public async Task<IReadOnlyList<BackupEntry>> ListBackupsAsync(string server, CancellationToken ct = default)
        => (await SendAsync(HttpMethod.Get, ServerPath(server) + "/backups", null, McJson.Default.BackupList, ct)).Backups;

    public Task<Job> CreateBackupAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/backups", null, McJson.Default.Job, ct);

    public Task<Job> RestoreBackupAsync(string server, string backup, bool confirm, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/backups/" + Ref(backup) + "/restore",
            new BackupRestoreRequest { Confirm = confirm }, McJson.Default.Job, ct);

    public async Task<IReadOnlyList<ModEntry>> ListModsAsync(string server, CancellationToken ct = default)
        => (await SendAsync(HttpMethod.Get, ServerPath(server) + "/mods", null, McJson.Default.ModList, ct)).Mods;

    public Task<Job> AddModAsync(string server, string reference, string? source = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/mods",
            new ModAddRequest { Ref = reference, Source = source }, McJson.Default.Job, ct);

    public Task<ModRemoved> RemoveModAsync(string server, string mod, bool confirmBlocks = false, CancellationToken ct = default)
        => SendAsync(HttpMethod.Delete, ServerPath(server) + "/mods/" + Ref(mod) + (confirmBlocks ? "?confirm_blocks=true" : ""),
            null, McJson.Default.ModRemoved, ct);

    public Task<Job> UpdateModsAsync(string server, string? name = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/mods/update", new ModUpdateRequest { Name = name }, McJson.Default.Job, ct);

    public Task<DatapackList> ListDatapacksAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/datapacks", null, McJson.Default.DatapackList, ct);

    public Task<DatapackSet> SetDatapackEnabledAsync(string server, string pack, bool enabled, string? placement = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Put, ServerPath(server) + "/datapacks/" + Ref(pack),
            new DatapackSetRequest
            {
                Enabled = enabled,
                First = enabled && placement == "first" ? true : null,
                Last = enabled && placement == "last" ? true : null,
                BeforeVanilla = enabled && placement == "before_vanilla" ? true : null,
            }, McJson.Default.DatapackSet, ct);

    public Task<WorldList> ListWorldsAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/worlds", null, McJson.Default.WorldList, ct);

    public Task<PregenProgress> GetPregenStatusAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/worlds/pregen", null, McJson.Default.PregenProgress, ct);

    public Task<Pregen> StartPregenAsync(string server, int radius, string? center = null, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/worlds/pregen",
            new PregenRequest { Radius = radius, Center = center }, McJson.Default.Pregen, ct);

    public Task<Job> ResetDimensionAsync(string server, string dimension, bool confirmed, bool includeOverworld, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/worlds/" + Ref(dimension) + "/reset",
            new WorldResetRequest { Confirmed = confirmed, IncludeOverworld = includeOverworld ? true : null }, McJson.Default.Job, ct);

    public async Task<IReadOnlyList<TaskEntry>> ListTasksAsync(string server, CancellationToken ct = default)
        => (await SendAsync(HttpMethod.Get, ServerPath(server) + "/tasks", null, McJson.Default.TaskList, ct)).Tasks;

    public Task<TaskCreated> CreateTaskAsync(string server, TaskCreateRequest request, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/tasks", request, McJson.Default.TaskCreated, ct);

    public Task<TaskCreated> UpdateTaskAsync(string server, int task, bool enabled, CancellationToken ct = default)
        => SendAsync(HttpMethod.Patch, ServerPath(server) + "/tasks/" + task,
            new TaskPatchRequest { Enabled = enabled }, McJson.Default.TaskCreated, ct);

    public Task<TaskCreated> DeleteTaskAsync(string server, int task, CancellationToken ct = default)
        => SendAsync(HttpMethod.Delete, ServerPath(server) + "/tasks/" + task, null, McJson.Default.TaskCreated, ct);

    public Task<Job> RunTaskAsync(string server, int task, bool skipWarn = false, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, ServerPath(server) + "/tasks/" + task + "/run",
            new TaskRunRequest { SkipWarn = skipWarn ? true : null }, McJson.Default.Job, ct);

    public Task<ConfigDocument> GetServerConfigAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/config", null, McJson.Default.ConfigDocument, ct);

    public Task<ConfigSet> SetConfigValueAsync(string server, string key, string value, CancellationToken ct = default)
        => SendAsync(HttpMethod.Put, ServerPath(server) + "/config/" + Ref(key),
            new ConfigSetRequest { Value = value }, McJson.Default.ConfigSet, ct);

    public Task<OperationResult> SetServerModeAsync(string server, string mode, CancellationToken ct = default)
        => SendAsync(HttpMethod.Put, ServerPath(server) + "/mode", new ModeRequest { Mode = mode }, McJson.Default.OperationResult, ct);

    public Task<OperationResult> SetServerScheduleAsync(string server, ScheduleRequest schedule, CancellationToken ct = default)
        => SendAsync(HttpMethod.Put, ServerPath(server) + "/schedule", schedule, McJson.Default.OperationResult, ct);

    public Task<SleepSettings> GetSleepSettingsAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/sleep", null, McJson.Default.SleepSettings, ct);

    public Task<SleepSettings> SetSleepSettingsAsync(string server, SleepSettingsRequest request, CancellationToken ct = default)
        => SendAsync(HttpMethod.Put, ServerPath(server) + "/sleep", request, McJson.Default.SleepSettings, ct);

    public Task<JavaRuntimes> ListServerJavaAsync(string server, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, ServerPath(server) + "/java", null, McJson.Default.JavaRuntimes, ct);

    public Task<JavaUsed> SetServerJavaAsync(string server, string choice, CancellationToken ct = default)
        => SendAsync(HttpMethod.Put, ServerPath(server) + "/java", new JavaUseRequest { Choice = choice }, McJson.Default.JavaUsed, ct);

    public Task<JavaRuntimes> ListJavaAsync(CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, "/v1/java", null, McJson.Default.JavaRuntimes, ct);

    public Task<Job> CreateServerAsync(CreateServerRequest request, CancellationToken ct = default)
        => SendAsync(HttpMethod.Post, "/v1/servers", request, McJson.Default.Job, ct);

    public async Task<IReadOnlyList<Job>> ListJobsAsync(string? state = null, CancellationToken ct = default)
    {
        var path = state is null ? "/v1/jobs" : "/v1/jobs?state=" + Ref(state);
        return (await SendAsync(HttpMethod.Get, path, null, McJson.Default.JobList, ct)).Jobs;
    }

    public Task<Job> GetJobAsync(string id, CancellationToken ct = default)
        => SendAsync(HttpMethod.Get, "/v1/jobs/" + Ref(id), null, McJson.Default.Job, ct);

    public async IAsyncEnumerable<ConsoleEvent> StreamConsoleAsync(
        string server, int tail = 200, [EnumeratorCancellation] CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, ServerPath(server) + "/console?tail=" + tail);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        HttpResponseMessage response;
        try
        {
            response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            throw new ApiException("daemon_unreachable", ex.Message, 0);
        }
        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                var text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                throw ParseError(text, (int)response.StatusCode);
            }
            await using var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            await foreach (var item in SseReader.ReadAsync(stream, ct).ConfigureAwait(false))
            {
                yield return item;
            }
        }
    }

    private async Task<T> SendAsync<T>(HttpMethod method, string path, object? body, JsonTypeInfo<T> info, CancellationToken ct)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null)
        {
            var json = JsonSerializer.Serialize(body, body.GetType(), McJson.Default);
            request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(RequestTimeout);
        string text;
        int status;
        try
        {
            using var response = await _http.SendAsync(request, timeout.Token).ConfigureAwait(false);
            status = (int)response.StatusCode;
            text = await response.Content.ReadAsStringAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (HttpRequestException ex)
        {
            throw new ApiException("daemon_unreachable", ex.Message, 0);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new ApiException("daemon_timeout", "", 0);
        }

        if (status is < 200 or >= 300)
        {
            throw ParseError(text, status);
        }
        try
        {
            using (var document = JsonDocument.Parse(text))
            {
                if (document.RootElement.ValueKind == JsonValueKind.Object
                    && document.RootElement.TryGetProperty("ok", out var ok)
                    && ok.ValueKind == JsonValueKind.False)
                {
                    throw ParseError(text, status);
                }
            }
            return JsonSerializer.Deserialize(text, info) ?? throw new ApiException("bad_answer", "", status);
        }
        catch (JsonException)
        {
            throw new ApiException("bad_answer", "", status);
        }
    }

    internal static ApiException ParseError(string text, int status)
    {
        try
        {
            var error = JsonSerializer.Deserialize(text, McJson.Default.ErrorBody);
            return new ApiException(error?.Code ?? "unknown", error?.Message ?? "", status);
        }
        catch (JsonException)
        {
            return new ApiException("bad_answer", "", status);
        }
    }
}
