using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class ServerItemViewModel : ObservableObject
{
    public ServerItemViewModel(string name)
    {
        Name = name;
    }

    public string Name { get; }

    [ObservableProperty]
    private string _state = "";

    [ObservableProperty]
    private string _version = "";

    [ObservableProperty]
    private string _playersText = "-";

    [ObservableProperty]
    private string _ramText = "-";

    [ObservableProperty]
    private bool _isActive;

    public void Update(ServerSnapshot snapshot, PlayersOnline? players)
    {
        State = snapshot.Error is not null ? "error" : snapshot.State ?? "";
        Version = string.Join(" ", new[] { snapshot.Loader, snapshot.Version }.Where(s => !string.IsNullOrEmpty(s)));
        IsActive = snapshot.Active;
        RamText = FormatRam(snapshot.RssKb);
        PlayersText = players is null
            ? "-"
            : players.Max is int max ? $"{players.Online}/{max}" : players.Online.ToString(CultureInfo.InvariantCulture);
    }

    public static string FormatRam(long? kb)
    {
        if (kb is null or <= 0)
        {
            return "-";
        }
        var megabytes = kb.Value / 1024.0;
        return megabytes >= 1024
            ? (megabytes / 1024.0).ToString("0.0", CultureInfo.InvariantCulture) + " GB"
            : megabytes.ToString("0", CultureInfo.InvariantCulture) + " MB";
    }
}
