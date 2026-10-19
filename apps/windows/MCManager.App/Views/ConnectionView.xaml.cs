using MCManager.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App.Views;

public sealed partial class ConnectionView : UserControl
{
    private ConnectionViewModel? _viewModel;

    public ConnectionView()
    {
        InitializeComponent();
    }

    public event Action? ConnectRequested;

    public ConnectionViewModel? ViewModel
    {
        get => _viewModel;
        set
        {
            _viewModel = value;
            TargetList.ItemsSource = value?.Targets;
            TargetList.SelectedItem = value?.Selected;
            UpdateButtons();
        }
    }

    private void UpdateButtons()
    {
        RemoveButton.IsEnabled = _viewModel is { Selected.IsLocal: false };
    }

    private void OnSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_viewModel is not null && TargetList.SelectedItem is ConnectionTarget target)
        {
            _viewModel.Selected = target;
        }
        UpdateButtons();
    }

    private void OnConnect(object sender, RoutedEventArgs e)
    {
        ConnectRequested?.Invoke();
    }

    private async void OnAdd(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }
        var wizard = new PairingWizardViewModel(_viewModel, Environment.MachineName);
        var dialog = new PairingDialog(wizard) { XamlRoot = XamlRoot };
        await dialog.ShowAsync();
        TargetList.SelectedItem = _viewModel.Selected;
        UpdateButtons();
    }

    private void OnRemove(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }
        _viewModel.RemoveSelected();
        TargetList.SelectedItem = _viewModel.Selected;
        UpdateButtons();
    }
}
