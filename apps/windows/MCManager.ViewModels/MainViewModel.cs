using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class MainViewModel : ObservableObject
{
    private readonly IMcClient? _client;

    public MainViewModel(IMcClient? client, ErrorReporter errors)
    {
        _client = client;
        Errors = errors;
        ServerList = client is null ? null : new ServerListViewModel(client, errors);
    }

    public ErrorReporter Errors { get; }

    public ServerListViewModel? ServerList { get; }

    [ObservableProperty]
    private ServerDetailViewModel? _detail;

    public bool IsConnected => _client is not null;

    public void OpenServer(string name)
    {
        if (_client is null)
        {
            return;
        }
        CloseDetail();
        Detail = new ServerDetailViewModel(_client, Errors, name);
    }

    public CreateServerViewModel? NewServer()
        => _client is null ? null : new CreateServerViewModel(_client, Errors);

    [RelayCommand]
    public void CloseDetail()
    {
        Detail?.Dispose();
        Detail = null;
    }
}
