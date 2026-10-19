using MCManager.Client;
using MCManager.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App;

public sealed partial class MainWindow : Window
{
    private readonly ErrorReporter _errors = new();
    private readonly ConnectionViewModel _connection;
    private MainViewModel _viewModel;
    private McClient? _remoteClient;
    private CancellationTokenSource _polling = new();

    public MainWindow()
    {
        InitializeComponent();
        Title = Strings.Get("AppTitle", "MC Manager");

        _errors.PropertyChanged += (_, _) => ShowError(_errors);
        var store = new ProfileStore(ProfileStore.DefaultPath(), new DpapiProtector());
        _connection = new ConnectionViewModel(
            store, new PairingClient(), Strings.Get("LocalMachine", "This machine"), LocalClient);
        _viewModel = new MainViewModel(null, _errors);

        ServersPage.ServerOpened += OnServerOpened;
        DetailPage.BackRequested += OnBackRequested;
        ConnectionPage.ViewModel = _connection;
        ConnectionPage.ConnectRequested += OnConnectRequested;
        Closed += OnClosed;
        Connect();
        Nav.SelectedItem = ServersItem;
    }

    private static IMcClient? LocalClient()
    {
        var endpoint = ApiLocator.Discover();
        return endpoint is null ? null : McClient.Create(endpoint);
    }

    private void Connect()
    {
        _polling.Cancel();
        DetailPage.Detach();
        _viewModel.CloseDetail();
        _remoteClient?.Dispose();
        _remoteClient = null;
        _errors.Clear();
        _polling = new CancellationTokenSource();

        IMcClient? client = null;
        try
        {
            client = _connection.CreateClient();
        }
        catch (ApiException ex)
        {
            _errors.Report(ex);
        }
        _remoteClient = _connection.Selected.IsLocal ? null : client as McClient;
        _viewModel = new MainViewModel(client, _errors);
        ServersPage.ViewModel = _viewModel.ServerList;
        if (_viewModel.ServerList is null)
        {
            if (!_errors.IsOpen)
            {
                _errors.Show("daemon_not_found", Strings.Get("DaemonNotFound"));
            }
        }
        else
        {
            _ = _viewModel.ServerList.RefreshAsync();
            _ = _viewModel.ServerList.PollAsync(TimeSpan.FromSeconds(5), _polling.Token);
        }
    }

    private void OnConnectRequested()
    {
        Connect();
        Nav.SelectedItem = ServersItem;
        ShowList();
    }

    private void ShowError(ErrorReporter errors)
    {
        ErrorBar.Message = Strings.Get("Error_" + errors.Code, errors.Message);
        ErrorBar.IsOpen = errors.IsOpen;
    }

    private void OnErrorClosed(InfoBar sender, InfoBarClosedEventArgs args)
    {
        _errors.Clear();
    }

    private void OnNavSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItemContainer?.Tag as string == "connection")
        {
            DetailPage.Detach();
            _viewModel.CloseDetail();
            DetailPage.Visibility = Visibility.Collapsed;
            ServersPage.Visibility = Visibility.Collapsed;
            ConnectionPage.Visibility = Visibility.Visible;
            return;
        }
        ShowList();
    }

    private void OnServerOpened(string name)
    {
        _viewModel.OpenServer(name);
        if (_viewModel.Detail is null)
        {
            return;
        }
        DetailPage.Attach(_viewModel.Detail);
        ServersPage.Visibility = Visibility.Collapsed;
        DetailPage.Visibility = Visibility.Visible;
    }

    private void OnBackRequested()
    {
        ShowList();
    }

    private void ShowList()
    {
        DetailPage.Detach();
        _viewModel.CloseDetail();
        DetailPage.Visibility = Visibility.Collapsed;
        ConnectionPage.Visibility = Visibility.Collapsed;
        ServersPage.Visibility = Visibility.Visible;
        if (_viewModel.ServerList is not null)
        {
            _ = _viewModel.ServerList.RefreshAsync();
        }
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        _polling.Cancel();
        DetailPage.Detach();
        _viewModel.CloseDetail();
        _remoteClient?.Dispose();
    }
}
