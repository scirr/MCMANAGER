using MCManager.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App.Views;

public sealed partial class SystemView : UserControl
{
    private SystemViewModel? _viewModel;

    public SystemView()
    {
        InitializeComponent();
        PairRoleBox.ItemsSource = DevicesViewModel.Roles;
        AccessKindBox.ItemsSource = RouterViewModel.AccessKinds;
    }

    public SystemViewModel? ViewModel => _viewModel;

    public void Attach(SystemViewModel viewModel)
    {
        _viewModel = viewModel;
        Bindings.Update();
        _ = viewModel.RefreshAsync();
    }

    public void Detach()
    {
        if (_viewModel is null)
        {
            return;
        }
        _viewModel = null;
        Bindings.Update();
    }

    private async void OnJavaRemoveClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: string major })
        {
            return;
        }
        var confirmed = await Dialogs.ConfirmAsync(
            XamlRoot, Strings.Get("JavaRemoveDialogTitle"), string.Format(Strings.Get("JavaRemoveDialogBody"), major), Strings.Get("JavaRemoveDialogConfirm"));
        await _viewModel.Java.RemoveAsync(major, confirmed);
    }

    private async void OnRemoteToggled(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && sender is ToggleSwitch toggle)
        {
            await _viewModel.Devices.SetRemoteAsync(toggle.IsOn);
        }
    }

    private void OnDeviceRoleLoaded(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not ComboBox { Tag: string id } box)
        {
            return;
        }
        var item = _viewModel.Devices.Items.FirstOrDefault(entry => entry.Id == id);
        if (item is null)
        {
            return;
        }
        box.SelectionChanged -= OnDeviceRoleChanged;
        box.ItemsSource = DevicesViewModel.Roles;
        box.SelectedItem = item.Role;
        AutomationProperties.SetName(box, string.Format(Strings.Get("DeviceRoleName"), item.Name));
        box.SelectionChanged += OnDeviceRoleChanged;
    }

    private async void OnDeviceRoleChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_viewModel is not null && sender is ComboBox { Tag: string id, SelectedItem: string role })
        {
            await _viewModel.Devices.SetRoleAsync(id, role);
        }
    }

    private async void OnDeviceRevokeClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: string id })
        {
            return;
        }
        var item = _viewModel.Devices.Items.FirstOrDefault(entry => entry.Id == id);
        if (item is null)
        {
            return;
        }
        var confirmed = await Dialogs.ConfirmAsync(
            XamlRoot, Strings.Get("DeviceRevokeDialogTitle"), string.Format(Strings.Get("DeviceRevokeDialogBody"), item.Name), Strings.Get("DeviceRevokeDialogConfirm"));
        await _viewModel.Devices.RevokeAsync(id, confirmed);
    }

    private async void OnRouterToggled(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null && sender is ToggleSwitch toggle)
        {
            await _viewModel.Router.ToggleAsync(toggle.IsOn);
        }
    }

    private async void OnRouterDefaultChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_viewModel is not null && sender is ComboBox { SelectedItem: string server })
        {
            await _viewModel.Router.SetDefaultAsync(server);
        }
    }

    private async void OnRouteRemoveClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: string host })
        {
            return;
        }
        var confirmed = await Dialogs.ConfirmAsync(
            XamlRoot, Strings.Get("RouteRemoveDialogTitle"), string.Format(Strings.Get("RouteRemoveDialogBody"), host), Strings.Get("RouteRemoveDialogConfirm"));
        await _viewModel.Router.RemoveRouteAsync(host, confirmed);
    }

    private async void OnAccessRemoveClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || sender is not FrameworkElement { Tag: string cidr })
        {
            return;
        }
        var entry = _viewModel.Router.Access.FirstOrDefault(item => item.Cidr == cidr);
        if (entry is not null)
        {
            await _viewModel.Router.EditAccessAsync(entry.Kind, "remove", cidr);
        }
    }

    private async void OnUpdateApplyClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }
        var confirmed = await Dialogs.ConfirmAsync(
            XamlRoot, Strings.Get("UpdateApplyDialogTitle"), string.Format(Strings.Get("UpdateApplyDialogBody"), _viewModel.Update.Latest), Strings.Get("UpdateApplyDialogConfirm"));
        await _viewModel.Update.ApplyAsync(confirmed);
    }

    private async void OnUpdateRollbackClick(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }
        var confirmed = await Dialogs.ConfirmAsync(
            XamlRoot, Strings.Get("UpdateRollbackDialogTitle"), Strings.Get("UpdateRollbackDialogBody"), Strings.Get("UpdateRollbackDialogConfirm"));
        await _viewModel.Update.RollbackAsync(confirmed);
    }
}
