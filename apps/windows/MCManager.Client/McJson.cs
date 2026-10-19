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
[JsonSerializable(typeof(ModList))]
[JsonSerializable(typeof(ModAddRequest))]
[JsonSerializable(typeof(ModUpdateRequest))]
[JsonSerializable(typeof(ModRemoved))]
[JsonSerializable(typeof(DatapackList))]
[JsonSerializable(typeof(DatapackSetRequest))]
[JsonSerializable(typeof(DatapackSet))]
[JsonSerializable(typeof(WorldList))]
[JsonSerializable(typeof(PregenProgress))]
[JsonSerializable(typeof(PregenRequest))]
[JsonSerializable(typeof(Pregen))]
[JsonSerializable(typeof(WorldResetRequest))]
[JsonSerializable(typeof(TaskList))]
[JsonSerializable(typeof(TaskCreated))]
[JsonSerializable(typeof(TaskCreateRequest))]
[JsonSerializable(typeof(TaskPatchRequest))]
[JsonSerializable(typeof(TaskRunRequest))]
[JsonSerializable(typeof(ConfigDocument))]
[JsonSerializable(typeof(ConfigSetRequest))]
[JsonSerializable(typeof(ConfigSet))]
[JsonSerializable(typeof(ModeRequest))]
[JsonSerializable(typeof(ScheduleRequest))]
[JsonSerializable(typeof(SleepSettings))]
[JsonSerializable(typeof(SleepSettingsRequest))]
[JsonSerializable(typeof(JavaRuntimes))]
[JsonSerializable(typeof(JavaUseRequest))]
[JsonSerializable(typeof(JavaUsed))]
[JsonSerializable(typeof(CreateServerRequest))]
[JsonSerializable(typeof(ErrorBody))]
[JsonSerializable(typeof(TokenFile))]
[JsonSerializable(typeof(PairRequest))]
[JsonSerializable(typeof(PairResult))]
[JsonSerializable(typeof(ProfileFile))]
[JsonSerializable(typeof(List<RemoteSummary>))]
internal sealed partial class McJson : JsonSerializerContext
{
}
