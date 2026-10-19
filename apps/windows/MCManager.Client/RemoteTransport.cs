using System.Net.Http.Headers;

namespace MCManager.Client;

public static class RemoteTransport
{
    public static Uri BaseAddress(string host, int port) => new UriBuilder("https", host, port).Uri;

    public static McClient Create(RemoteProfile profile)
    {
        if (!Fingerprint.IsValid(profile.Fingerprint) || string.IsNullOrEmpty(profile.Token))
        {
            throw new ApiException("fingerprint_missing", "", 0);
        }
        var http = new HttpClient(PinnedHttpHandler.Create(profile.Fingerprint), true)
        {
            BaseAddress = BaseAddress(profile.Host, profile.Port),
            Timeout = Timeout.InfiniteTimeSpan,
        };
        http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", profile.Token);
        return new McClient(http, true);
    }
}
