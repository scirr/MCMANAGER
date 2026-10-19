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
[JsonSerializable(typeof(BackupList))]
[JsonSerializable(typeof(BackupRestoreRequest))]
[JsonSerializable(typeof(StopRequest))]
[JsonSerializable(typeof(ConsoleCommand))]
[JsonSerializable(typeof(PlayerListAdd))]
[JsonSerializable(typeof(KickRequest))]
[JsonSerializable(typeof(ErrorBody))]
[JsonSerializable(typeof(TokenFile))]
[JsonSerializable(typeof(PairRequest))]
[JsonSerializable(typeof(PairResult))]
[JsonSerializable(typeof(ProfileFile))]
[JsonSerializable(typeof(List<RemoteSummary>))]
internal sealed partial class McJson : JsonSerializerContext
{
}
