using MCManager.ViewModels;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App.Views;

public sealed partial class ServersView : UserControl
{
    private ServerListViewModel? _viewModel;

    public ServersView()
    {
        InitializeComponent();
    }

    public event Action<string>? ServerOpened;

    public event Action? CreateRequested;

    public ServerListViewModel? ViewModel
    {
        get => _viewModel;
        set
        {
            _viewModel = value;
            Bindings.Update();
        }
    }

    private void OnCreateClick(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        CreateRequested?.Invoke();
    }

    private void OnItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is ServerItemViewModel item)
        {
            ServerOpened?.Invoke(item.Name);
        }
    }
}
