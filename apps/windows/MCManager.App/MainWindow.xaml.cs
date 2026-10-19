using MCManager.Client;
using MCManager.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App;

public sealed partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;
    private readonly CancellationTokenSource _polling = new();

    public MainWindow()
    {
        InitializeComponent();
        Title = Strings.Get("AppTitle", "MC Manager");

        var errors = new ErrorReporter();
        errors.PropertyChanged += (_, _) => ShowError(errors);
        var endpoint = ApiLocator.Discover();
        IMcClient? client = endpoint is null ? null : McClient.Create(endpoint);
        _viewModel = new MainViewModel(client, errors);

        ServersPage.ViewModel = _viewModel.ServerList;
        ServersPage.ServerOpened += OnServerOpened;
        DetailPage.BackRequested += OnBackRequested;
        Closed += OnClosed;
        Nav.SelectedItem = ServersItem;

        if (_viewModel.ServerList is null)
        {
            errors.Show("daemon_not_found", Strings.Get("DaemonNotFound"));
        }
        else
        {
            _ = _viewModel.ServerList.RefreshAsync();
            _ = _viewModel.ServerList.PollAsync(TimeSpan.FromSeconds(5), _polling.Token);
        }
    }

    private void ShowError(ErrorReporter errors)
    {
        ErrorBar.Message = errors.Message;
        ErrorBar.IsOpen = errors.IsOpen;
    }

    private void OnErrorClosed(InfoBar sender, InfoBarClosedEventArgs args)
    {
        _viewModel.Errors.Clear();
    }

    private void OnNavSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
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
    }
}
