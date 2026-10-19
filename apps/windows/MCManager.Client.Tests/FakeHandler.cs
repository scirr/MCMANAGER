using System.Net;
using System.Text;

namespace MCManager.Client.Tests;

internal sealed class FakeHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, string?, (HttpStatusCode, string, string)> _respond;

    public FakeHandler(Func<HttpRequestMessage, string?, (HttpStatusCode, string, string)> respond)
    {
        _respond = respond;
    }

    public static FakeHandler Json(HttpStatusCode status, string body)
        => new((_, _) => (status, body, "application/json"));

    public List<(HttpMethod Method, string Path, string? Body)> Requests { get; } = new();

    public HttpRequestMessage? Last { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
        Requests.Add((request.Method, request.RequestUri!.PathAndQuery, body));
        Last = request;
        var (status, text, type) = _respond(request, body);
        return new HttpResponseMessage(status) { Content = new StringContent(text, Encoding.UTF8, type) };
    }

    public McClient Client()
        => new(new HttpClient(this) { BaseAddress = new Uri("http://127.0.0.1:1/") });
}
