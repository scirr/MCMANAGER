using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record DatapackItem(string File, string Id, bool Enabled, bool CanToggle, string? Problem, bool Worldgen, bool CanWrite = true);

public sealed partial class DatapacksViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Placements = new[] { "default", "first", "last", "before_vanilla" };

    public DatapacksViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
    }

    public ObservableCollection<DatapackItem> Items { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    [ObservableProperty]
    private bool _serverRunning;

    [ObservableProperty]
    private string _placement = "default";

    protected override void ReadOnlyChanged() => Replace(Items, item => item with { CanWrite = !IsReadOnly });

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await Errors.TryAsync(async () =>
        {
            var list = await Api.ListDatapacksAsync(Server);
            ServerRunning = list.Running;
            Items.Clear();
            foreach (var pack in list.Packs)
            {
                Items.Add(new DatapackItem(pack.File, pack.Id, pack.Enabled == true, pack.Problem is null, pack.Problem, pack.Worldgen, !IsReadOnly));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    public async Task SetEnabledAsync(string? file, bool enabled)
    {
        if (string.IsNullOrEmpty(file) || IsBusy)
        {
            return;
        }
        IsBusy = true;
        try
        {
            await WriteAsync(async () =>
            {
                var set = await Api.SetDatapackEnabledAsync(Server, file, enabled, enabled && Placement != "default" ? Placement : null);
                if (set.RestartRequired)
                {
                    RestartRequired = true;
                }
            });
        }
        finally
        {
            IsBusy = false;
        }
        await RefreshAsync();
    }
}
