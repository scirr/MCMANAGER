using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class PlayersViewModel : ObservableObject
{
    public static readonly IReadOnlyList<string> Kinds = new[] { "whitelist", "op", "ban", "banip" };

    private readonly IMcClient _client;
    private readonly ErrorReporter _errors;
    private readonly string _server;

    public PlayersViewModel(IMcClient client, ErrorReporter errors, string server)
    {
        _client = client;
        _errors = errors;
        _server = server;
    }

    public ObservableCollection<string> Online { get; } = new();

    public ObservableCollection<PlayerListEntry> Entries { get; } = new();

    [ObservableProperty]
    private string _onlineText = "-";

    [ObservableProperty]
    private string _selectedKind = "whitelist";

    [ObservableProperty]
    private string _newSubject = "";

    [ObservableProperty]
    private string _reason = "";

    partial void OnSelectedKindChanged(string value)
    {
        _ = LoadListAsync();
    }

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await LoadOnlineAsync();
        await LoadListAsync();
    }

    public async Task LoadOnlineAsync()
    {
        try
        {
            var players = await _client.GetOnlinePlayersAsync(_server);
            Online.Clear();
            foreach (var name in players.Players)
            {
                Online.Add(name);
            }
            OnlineText = players.Max is int max ? $"{players.Online}/{max}" : players.Online.ToString();
        }
        catch (ApiException ex) when (ex.Code is "server_offline" or "rcon_failed" or "rcon_error")
        {
            Online.Clear();
            OnlineText = "-";
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _errors.Report(ex);
        }
    }

    public async Task LoadListAsync()
    {
        await _errors.TryAsync(async () =>
        {
            var listing = await _client.GetPlayerListAsync(_server, SelectedKind);
            Entries.Clear();
            foreach (var entry in listing.Entries)
            {
                Entries.Add(entry);
            }
        });
    }

    [RelayCommand]
    public async Task AddAsync()
    {
        var subject = NewSubject.Trim();
        if (subject.Length == 0)
        {
            return;
        }
        var reason = Reason.Trim();
        var ok = await _errors.TryAsync(async () =>
            await _client.AddPlayerListEntryAsync(_server, SelectedKind, subject, reason.Length == 0 ? null : reason));
        if (ok)
        {
            NewSubject = "";
            Reason = "";
            await LoadListAsync();
        }
    }

    [RelayCommand]
    public async Task RemoveAsync(string? subject)
    {
        if (string.IsNullOrEmpty(subject))
        {
            return;
        }
        if (await _errors.TryAsync(async () => await _client.RemovePlayerListEntryAsync(_server, SelectedKind, subject)))
        {
            await LoadListAsync();
        }
    }

    [RelayCommand]
    public async Task KickAsync(string? player)
    {
        if (string.IsNullOrEmpty(player))
        {
            return;
        }
        if (await _errors.TryAsync(async () => await _client.KickPlayerAsync(_server, player)))
        {
            await LoadOnlineAsync();
        }
    }
}
