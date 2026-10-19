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
