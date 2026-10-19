using System.Text.Json;
using System.Text.Json.Serialization;

namespace MCManager.Client;

[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    PropertyNameCaseInsensitive = true)]
[JsonSerializable(typeof(ServerSnapshot))]
[JsonSerializable(typeof(ServerList))]
[JsonSerializable(typeof(PlayersOnline))]
[JsonSerializable(typeof(PlayerListing))]
[JsonSerializable(typeof(OperationResult))]
[JsonSerializable(typeof(Job))]
[JsonSerializable(typeof(JobList))]
[JsonSerializable(typeof(StopRequest))]
[JsonSerializable(typeof(ConsoleCommand))]
[JsonSerializable(typeof(PlayerListAdd))]
[JsonSerializable(typeof(KickRequest))]
[JsonSerializable(typeof(ErrorBody))]
[JsonSerializable(typeof(TokenFile))]
internal sealed partial class McJson : JsonSerializerContext
{
}
