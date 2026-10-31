using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MCManager.App;

internal static class Dialogs
{
    public static async Task<bool> ConfirmAsync(XamlRoot root, string title, string body, string confirm)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = root,
            Title = title,
            Content = body,
            PrimaryButtonText = confirm,
            CloseButtonText = Strings.Get("RestoreDialogCancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
}
