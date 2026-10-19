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
        ModSourceBox.ItemsSource = ModsViewModel.Sources;
        TaskActionBox.ItemsSource = TasksViewModel.Actions;
        ModeBox.ItemsSource = SettingsViewModel.Modes;
        SleepJoinBox.ItemsSource = SettingsViewModel.JoinModes;
        DatapackPlacementBox.ItemsSource = DatapacksViewModel.Placements;
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
        _ = viewModel.Mods.RefreshAsync();
        _ = viewModel.Datapacks.RefreshAsync();
        _ = viewModel.World.RefreshAsync();
        _ = viewModel.Tasks.RefreshAsync();
        _ = viewModel.Settings.RefreshAsync();
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

    private async Task<bool> ConfirmAsync(string title, string body, string confirm)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = title,
            Content = body,
            PrimaryButtonText = confirm,
            CloseButtonText = Strings.Get("RestoreDialogCancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }

    private async void OnRestoreClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || !_viewModel.Backups.CanAct || sender is not FrameworkElement { Tag: string id })
        {
            return;
        }
        var item = _viewModel.Backups.Items.FirstOrDefault(entry => entry.Id == id);
        if (item is null)
        {
            return;
        }
        var confirmed = await ConfirmAsync(
            Strings.Get("RestoreDialogTitle"), string.Format(Strings.Get("RestoreDialogBody"), item.Date), Strings.Get("RestoreDialogConfirm"));
        await _viewModel.Backups.RestoreAsync(item.Id, confirmed);
    }

    private async void OnModRemoveClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: string file })
        {
            return;
        }
        var item = _viewModel.Mods.Items.FirstOrDefault(entry => entry.File == file);
        if (item is null)
        {
            return;
        }
        var body = string.Format(Strings.Get("ModRemoveDialogBody"), item.Name);
        if (item.AddsBlocks)
        {
            body += "\n\n" + Strings.Get("ModRemoveBlocksWarning");
        }
        var confirmed = await ConfirmAsync(Strings.Get("ModRemoveDialogTitle"), body, Strings.Get("ModRemoveDialogConfirm"));
        await _viewModel.Mods.RemoveAsync(item.File, confirmed);
    }

    private void OnDatapackToggleClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: string file })
        {
            return;
        }
        var item = _viewModel.Datapacks.Items.FirstOrDefault(entry => entry.File == file);
        if (item is not null)
        {
            _ = _viewModel.Datapacks.SetEnabledAsync(item.File, !item.Enabled);
        }
    }

    private async void OnResetDimensionClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || !_viewModel.World.CanAct || sender is not FrameworkElement { Tag: string id })
        {
            return;
        }
        var body = string.Format(Strings.Get("ResetDialogBody"), Strings.Dimension(id));
        var confirmed = await ConfirmAsync(Strings.Get("ResetDialogTitle"), body, Strings.Get("ResetDialogConfirm"));
        await _viewModel.World.ResetAsync(id, confirmed);
    }

    private void OnTaskToggleClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: int id })
        {
            return;
        }
        var item = _viewModel.Tasks.Items.FirstOrDefault(entry => entry.Id == id);
        if (item is not null)
        {
            _ = _viewModel.Tasks.SetEnabledAsync(item.Id, !item.Enabled);
        }
    }

    private void OnTaskRunClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && _viewModel.Tasks.CanAct && sender is FrameworkElement { Tag: int id })
        {
            _ = _viewModel.Tasks.RunAsync(id);
        }
    }

    private async void OnTaskDeleteClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: int id })
        {
            return;
        }
        var item = _viewModel.Tasks.Items.FirstOrDefault(entry => entry.Id == id);
        if (item is null)
        {
            return;
        }
        var confirmed = await ConfirmAsync(
            Strings.Get("TaskDeleteDialogTitle"), string.Format(Strings.Get("TaskDeleteDialogBody"), item.Name), Strings.Get("TaskDeleteDialogConfirm"));
        await _viewModel.Tasks.DeleteAsync(item.Id, confirmed);
    }

    private void OnModeChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_viewModel is not null && ModeBox.SelectedItem is string mode)
        {
            _ = _viewModel.Settings.SetModeAsync(mode);
        }
    }

    private void OnRemoveClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && sender is FrameworkElement { Tag: string subject })
        {
            _viewModel.Players.RemoveCommand.Execute(subject);
        }
    }
}
