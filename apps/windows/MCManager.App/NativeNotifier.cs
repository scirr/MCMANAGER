using MCManager.ViewModels;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppNotifications.Builder;

namespace MCManager.App;

internal sealed class NativeNotifier
{
    private bool _registered;

    public event Action? Invoked;

    public void Register()
    {
        try
        {
            AppNotificationManager.Default.NotificationInvoked += (_, _) => Invoked?.Invoke();
            AppNotificationManager.Default.Register();
            _registered = true;
        }
        catch (Exception)
        {
            _registered = false;
        }
    }

    public void Unregister()
    {
        if (!_registered)
        {
            return;
        }
        try
        {
            AppNotificationManager.Default.Unregister();
        }
        catch (Exception)
        {
        }
        _registered = false;
    }

    public void Show(AppNotice notice)
    {
        if (!_registered)
        {
            return;
        }
        try
        {
            var builder = new AppNotificationBuilder().AddText(Strings.NotifyTitle(notice.Kind, notice.Server));
            if (notice.Detail.Length > 0)
            {
                builder.AddText(notice.Detail);
            }
            var notification = builder.BuildNotification();
            notification.Tag = notice.Id;
            AppNotificationManager.Default.Show(notification);
        }
        catch (Exception)
        {
        }
    }
}
