using System.ComponentModel;
using MCManager.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App.Views;

public sealed partial class CreateServerView : UserControl
{
    private CreateServerViewModel? _viewModel;

    public CreateServerView()
    {
        InitializeComponent();
        CreateLoaderBox.ItemsSource = CreateServerViewModel.Loaders;
    }

    public event Action? BackRequested;

    public event Action<string>? Created;

    public CreateServerViewModel? ViewModel => _viewModel;

    public void Attach(CreateServerViewModel viewModel)
    {
        Detach();
        _viewModel = viewModel;
        viewModel.PropertyChanged += OnPropertyChanged;
        Bindings.Update();
    }

    public void Detach()
    {
        if (_viewModel is null)
        {
            return;
        }
        _viewModel.PropertyChanged -= OnPropertyChanged;
        _viewModel = null;
        Bindings.Update();
    }

    private void OnPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(CreateServerViewModel.CreatedName) && _viewModel is { CreatedName.Length: > 0 } viewModel)
        {
            Created?.Invoke(viewModel.CreatedName);
        }
    }

    private void OnBackClick(object sender, RoutedEventArgs e)
    {
        BackRequested?.Invoke();
    }
}
