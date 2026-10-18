using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class ServerListViewModel : ObservableObject
{
    private readonly IMcClient _client;
    private readonly ErrorReporter _errors;

    public ServerListViewModel(IMcClient client, ErrorReporter errors)
    {
        _client = client;
        _errors = errors;
    }

    public ObservableCollection<ServerItemViewModel> Servers { get; } = new();

    [ObservableProperty]
    private bool _isLoading;

    [ObservableProperty]
    private bool _isEmpty;

    [RelayCommand]
    public async Task RefreshAsync()
    {
        IsLoading = true;
        try
        {
            await _errors.TryAsync(async () =>
            {
                var snapshots = await _client.ListServersAsync();
                var names = snapshots.Select(s => s.Name).ToHashSet();
                for (var i = Servers.Count - 1; i >= 0; i--)
                {
                    if (!names.Contains(Servers[i].Name))
                    {
                        Servers.RemoveAt(i);
                    }
                }
                foreach (var snapshot in snapshots)
                {
                    var item = Servers.FirstOrDefault(s => s.Name == snapshot.Name);
                    if (item is null)
                    {
                        item = new ServerItemViewModel(snapshot.Name);
                        Servers.Add(item);
                    }
                    item.Update(snapshot, await PlayersOrNullAsync(snapshot));
                }
                IsEmpty = Servers.Count == 0;
            });
        }
        finally
        {
            IsLoading = false;
        }
    }

    public async Task PollAsync(TimeSpan interval, CancellationToken ct)
    {
        using var timer = new PeriodicTimer(interval);
        try
        {
            while (await timer.WaitForNextTickAsync(ct))
            {
                await RefreshAsync();
            }
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task<PlayersOnline?> PlayersOrNullAsync(ServerSnapshot snapshot)
    {
        if (snapshot.State != "running")
        {
            return null;
        }
        try
        {
            return await _client.GetOnlinePlayersAsync(snapshot.Name);
        }
        catch (ApiException)
        {
            return null;
        }
    }
}
