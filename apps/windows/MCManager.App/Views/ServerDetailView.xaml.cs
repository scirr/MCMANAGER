using System.Collections.Specialized;
using MCManager.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.System;

namespace MCManager.App.Views;

public sealed partial class ServerDetailView : UserControl
{
    private ServerDetailViewModel? _viewModel;
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(3) };

    public ServerDetailView()
    {
        InitializeComponent();
        KindBox.ItemsSource = PlayersViewModel.Kinds;
        _timer.Tick += OnTick;
    }

    public event Action? BackRequested;

    public ServerDetailViewModel? ViewModel => _viewModel;

    public void Attach(ServerDetailViewModel viewModel)
    {
        Detach();
        _viewModel = viewModel;
        Bindings.Update();
        viewModel.Console.Lines.CollectionChanged += OnLinesChanged;
        viewModel.Console.Start();
        _ = viewModel.RefreshAsync();
        _ = viewModel.Players.LoadListAsync();
        _ = viewModel.Backups.RefreshAsync();
        _timer.Start();
    }

    public void Detach()
    {
        _timer.Stop();
        if (_viewModel is null)
        {
            return;
        }
        _viewModel.Console.Lines.CollectionChanged -= OnLinesChanged;
        _viewModel = null;
        Bindings.Update();
    }

    private void OnTick(object? sender, object e)
    {
        if (_viewModel is not null)
        {
            _ = _viewModel.RefreshAsync();
        }
    }

    private void OnLinesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        var lines = _viewModel?.Console.Lines;
        if (lines is { Count: > 0 })
        {
            ConsoleList.ScrollIntoView(lines[^1]);
        }
    }

    private void OnBackClick(object sender, RoutedEventArgs e)
    {
        BackRequested?.Invoke();
    }

    private void OnConsoleKeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter && _viewModel is not null)
        {
            e.Handled = true;
            _viewModel.Console.CommandText = ConsoleInput.Text;
            _viewModel.Console.SendCommand.Execute(null);
        }
    }

    private void OnKickClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && sender is FrameworkElement { Tag: string player })
        {
            _viewModel.Players.KickCommand.Execute(player);
        }
    }

    private async void OnRestoreClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: BackupItem item })
        {
            return;
        }
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = Strings.Get("RestoreDialogTitle"),
            Content = string.Format(Strings.Get("RestoreDialogBody"), item.Date),
            PrimaryButtonText = Strings.Get("RestoreDialogConfirm"),
            CloseButtonText = Strings.Get("RestoreDialogCancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        var answer = await dialog.ShowAsync();
        await _viewModel.Backups.RestoreAsync(item.Id, answer == ContentDialogResult.Primary);
    }

    private void OnRemoveClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && sender is FrameworkElement { Tag: string subject })
        {
            _viewModel.Players.RemoveCommand.Execute(subject);
        }
    }
}
