using System.Runtime.CompilerServices;
using System.Text;

namespace MCManager.Client;

public static class SseReader
{
    public static async IAsyncEnumerable<ConsoleEvent> ReadAsync(
        Stream stream, [EnumeratorCancellation] CancellationToken ct = default)
    {
        using var reader = new StreamReader(stream, Encoding.UTF8);
        string? name = null;
        string? id = null;
        var data = new List<string>();
        while (true)
        {
            var line = await reader.ReadLineAsync(ct).ConfigureAwait(false);
            if (line is null)
            {
                yield break;
            }
            if (line.Length == 0)
            {
                if (name is not null || data.Count > 0)
                {
                    yield return new ConsoleEvent(id, name ?? "message", string.Join("\n", data));
                }
                name = null;
                data.Clear();
                continue;
            }
            if (line[0] == ':')
            {
                continue;
            }
            var colon = line.IndexOf(':');
            var key = colon < 0 ? line : line[..colon];
            var value = colon < 0 ? "" : line[(colon + 1)..];
            if (value.StartsWith(' '))
            {
                value = value[1..];
            }
            switch (key)
            {
                case "event":
                    name = value;
                    break;
                case "data":
                    data.Add(value);
                    break;
                case "id":
                    id = value;
                    break;
            }
        }
    }
}
