using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record JavaRuntimeItem(string Major, string Path, string Servers, bool CanWrite = true);

public sealed partial class JavaViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Majors = new[] { "8", "11", "17", "21", "25" };

    public JavaViewModel(IMcClient client, ErrorReporter errors)
        : base(client, errors, "")
    {
    }

    public ObservableCollection<JavaRuntimeItem> Items { get; } = new();

    public ObservableCollection<string> Installable { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    protected override void ReadOnlyChanged() => Replace(Items, item => item with { CanWrite = !IsReadOnly });

    [ObservableProperty]
    private string _selectedMajor = "";

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await ReadAsync(async () =>
        {
            var document = await Api.ListJavaAsync();
            Items.Clear();
            foreach (var major in document.Runtimes.Keys.OrderBy(k => k.Length).ThenBy(k => k, StringComparer.Ordinal))
            {
                var users = document.Servers.Where(s => s.JavaText == major).Select(s => s.Server);
                Items.Add(new JavaRuntimeItem(major, document.Runtimes[major], string.Join(", ", users), !IsReadOnly));
            }
            Installable.Clear();
            foreach (var major in Majors.Where(m => !document.Runtimes.ContainsKey(m)))
            {
                Installable.Add(major);
            }
            if (!Installable.Contains(SelectedMajor))
            {
                SelectedMajor = Installable.FirstOrDefault() ?? "";
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    [RelayCommand]
    public async Task InstallAsync()
    {
        if (!int.TryParse(SelectedMajor, out var major) || major < 8)
        {
            Errors.Show("java_unknown_version", "");
            return;
        }
        if (await RunJobAsync("java_installed", () => Api.InstallJavaAsync(major)))
        {
            await RefreshAsync();
        }
    }

    public async Task RemoveAsync(string major, bool confirmed)
    {
        if (!confirmed || !int.TryParse(major, out var number))
        {
            return;
        }
        if (await WriteAsync(async () => await Api.RemoveJavaAsync(number)))
        {
            LastDone = "java_removed";
            await RefreshAsync();
        }
    }
}

public sealed record DeviceItem(string Id, string Name, string Role, string LastIp, string LastSeen, string Servers, bool CanWrite = true)
{
    public bool ReadOnly => !CanWrite;
}

public sealed record AuditItem(string At, string Action, string Device, string Server, bool Ok);

public sealed partial class DevicesViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Roles = new[] { "viewer", "operator", "admin" };

    public DevicesViewModel(IMcClient client, ErrorReporter errors)
        : base(client, errors, "")
    {
    }

    public ObservableCollection<DeviceItem> Items { get; } = new();

    public ObservableCollection<AuditItem> Audit { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    public bool AuditEmpty => Audit.Count == 0;

    protected override void ReadOnlyChanged() => Replace(Items, item => item with { CanWrite = !IsReadOnly });

    [ObservableProperty]
    private bool _remoteEnabled;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasFingerprint))]
    private string _fingerprint = "";

    public bool HasFingerprint => Fingerprint.Length > 0;

    [ObservableProperty]
    private string _pairName = "";

    [ObservableProperty]
    private string _pairRole = "operator";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasCode))]
    private string _code = "";

    [ObservableProperty]
    private int _codeMinutes;

    public bool HasCode => Code.Length > 0;

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await ReadAsync(async () =>
        {
            var devices = await Api.ListDevicesAsync();
            Items.Clear();
            foreach (var device in devices.Devices.Where(d => !d.Revoked))
            {
                Items.Add(new DeviceItem(
                    device.Id,
                    string.IsNullOrEmpty(device.Name) ? device.Id : device.Name,
                    device.Roles.Default,
                    device.LastIp ?? "",
                    (device.LastSeen ?? "").Replace('T', ' '),
                    device.Servers is { Count: > 0 } ? string.Join(", ", device.Servers) : "",
                    !IsReadOnly));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
        await ReadAsync(async () =>
        {
            var status = await Api.GetRemoteStatusAsync();
            RemoteEnabled = status.Enabled;
            Fingerprint = status.Fingerprint ?? "";
        });
        await ReadAsync(async () =>
        {
            var log = await Api.ListAuditLogAsync(50);
            Audit.Clear();
            foreach (var entry in log.Entries)
            {
                Audit.Add(new AuditItem(entry.At.Replace('T', ' '), entry.Action, entry.Device ?? "", entry.Server ?? "", entry.Ok));
            }
            OnPropertyChanged(nameof(AuditEmpty));
        });
    }

    public async Task SetRemoteAsync(bool enabled)
    {
        if (enabled == RemoteEnabled)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.SetRemoteAccessAsync(enabled)))
        {
            LastDone = enabled ? "remote_on" : "remote_off";
            await RefreshAsync();
        }
        OnPropertyChanged(nameof(RemoteEnabled));
    }

    [RelayCommand]
    public async Task NewCodeAsync()
    {
        if (!Roles.Contains(PairRole))
        {
            return;
        }
        Code = "";
        var name = PairName.Trim();
        PairingCodeDocument? document = null;
        if (await WriteAsync(async () => document = await Api.CreatePairingCodeAsync(PairRole, name.Length == 0 ? null : name)) && document is not null)
        {
            Code = document.PairingCode;
            CodeMinutes = Math.Max(1, document.ExpiresInS / 60);
            LastDone = "code";
        }
    }

    public async Task SetRoleAsync(string device, string role)
    {
        if (!Roles.Contains(role) || Items.FirstOrDefault(d => d.Id == device)?.Role == role)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.SetDeviceRoleAsync(device, role)))
        {
            LastDone = "role";
        }
        await RefreshAsync();
    }

    public async Task RevokeAsync(string device, bool confirmed)
    {
        if (!confirmed || device.Length == 0)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.RevokeDeviceAsync(device)))
        {
            LastDone = "revoked";
            await RefreshAsync();
        }
    }
}

public sealed partial class UpdateViewModel : TabViewModel
{
    public UpdateViewModel(IMcClient client, ErrorReporter errors)
        : base(client, errors, "")
    {
    }

    [ObservableProperty]
    private string _current = "";

    [ObservableProperty]
    private string _latest = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanApply))]
    private bool _available;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanRollback))]
    private bool _rollbackAvailable;

    public bool CanApply => Available && CanAct;

    public bool CanRollback => RollbackAvailable && CanAct;

    protected override void BusyChanged()
    {
        OnPropertyChanged(nameof(CanApply));
        OnPropertyChanged(nameof(CanRollback));
    }

    protected override void ReadOnlyChanged()
    {
        OnPropertyChanged(nameof(CanApply));
        OnPropertyChanged(nameof(CanRollback));
    }

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await ReadAsync(async () =>
        {
            var info = await Api.CheckUpdateAsync();
            Current = info.Current;
            Latest = info.Latest;
            Available = info.UpdateAvailable;
            RollbackAvailable = info.RollbackAvailable;
        });
    }

    public async Task ApplyAsync(bool confirmed)
    {
        if (!confirmed || !CanApply)
        {
            return;
        }
        if (await RunJobAsync("update", () => Api.ApplyUpdateAsync()))
        {
            await RefreshAsync();
        }
    }

    public async Task RollbackAsync(bool confirmed)
    {
        if (!confirmed || !CanRollback)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.RollbackUpdateAsync()))
        {
            LastDone = "rollback";
            await RefreshAsync();
        }
    }
}

public sealed record DoctorItem(string Server, string Name, string Level, string Detail, string Fix);

public sealed partial class DoctorViewModel : TabViewModel
{
    public DoctorViewModel(IMcClient client, ErrorReporter errors)
        : base(client, errors, "")
    {
    }

    public ObservableCollection<DoctorItem> Items { get; } = new();

    [ObservableProperty]
    private bool _hasRun;

    [ObservableProperty]
    private int _errorCount;

    [ObservableProperty]
    private int _warningCount;

    [RelayCommand]
    public async Task RunAsync()
    {
        if (IsBusy)
        {
            return;
        }
        IsBusy = true;
        try
        {
            await ReadAsync(async () =>
            {
                var report = await Api.GetDoctorReportAsync();
                Items.Clear();
                foreach (var check in report.Checks)
                {
                    Items.Add(new DoctorItem(
                        check.Server ?? "",
                        check.Name,
                        check.Level ?? (check.Ok ? "ok" : "err"),
                        check.Detail ?? "",
                        check.Fix ?? ""));
                }
                ErrorCount = report.Errors;
                WarningCount = report.Warnings;
                HasRun = true;
                LastDone = "doctor";
            });
        }
        finally
        {
            IsBusy = false;
        }
    }
}

public sealed record RouteItem(string Host, string Server, bool CanWrite = true);

public sealed record AccessItem(string Kind, string Cidr, bool CanWrite = true);

public sealed partial class RouterViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> AccessKinds = new[] { "allow", "deny" };

    public RouterViewModel(IMcClient client, ErrorReporter errors)
        : base(client, errors, "")
    {
    }

    public ObservableCollection<RouteItem> Routes { get; } = new();

    public ObservableCollection<AccessItem> Access { get; } = new();

    public ObservableCollection<string> ServerNames { get; } = new();

    public bool RoutesEmpty => Routes.Count == 0;

    protected override void ReadOnlyChanged()
    {
        Replace(Routes, item => item with { CanWrite = !IsReadOnly });
        Replace(Access, item => item with { CanWrite = !IsReadOnly });
    }

    [ObservableProperty]
    private bool _enabled;

    [ObservableProperty]
    private string _defaultServer = "";

    [ObservableProperty]
    private string _pending = "";

    [ObservableProperty]
    private string _newHost = "";

    [ObservableProperty]
    private string _newServer = "";

    [ObservableProperty]
    private string _accessKind = "allow";

    [ObservableProperty]
    private string _newCidr = "";

    private void Apply(RouterDocument document)
    {
        var config = document.Config;
        Enabled = config.Enabled;
        DefaultServer = config.Default ?? "";
        Pending = string.Join(", ", document.PendingRestart);
        Routes.Clear();
        foreach (var route in config.Routes.OrderBy(r => r.Key, StringComparer.Ordinal))
        {
            Routes.Add(new RouteItem(route.Key, route.Value, !IsReadOnly));
        }
        Access.Clear();
        foreach (var cidr in config.Allow)
        {
            Access.Add(new AccessItem("allow", cidr, !IsReadOnly));
        }
        foreach (var cidr in config.Deny)
        {
            Access.Add(new AccessItem("deny", cidr, !IsReadOnly));
        }
        OnPropertyChanged(nameof(RoutesEmpty));
    }

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await ReadAsync(async () =>
        {
            var servers = await Api.ListServersAsync();
            ServerNames.Clear();
            foreach (var server in servers)
            {
                ServerNames.Add(server.Name);
            }
            Apply(await Api.GetRouterAsync());
            if (!ServerNames.Contains(NewServer))
            {
                NewServer = ServerNames.FirstOrDefault() ?? "";
            }
            OnPropertyChanged(nameof(DefaultServer));
            OnPropertyChanged(nameof(NewServer));
        });
    }

    private async Task ChangeAsync(Func<Task<RouterDocument>> action, string done)
    {
        RouterDocument? document = null;
        if (await WriteAsync(async () => document = await action()) && document is not null)
        {
            LastDone = done;
            Apply(document);
        }
        OnPropertyChanged(nameof(Enabled));
        OnPropertyChanged(nameof(DefaultServer));
    }

    public async Task ToggleAsync(bool enabled)
    {
        if (enabled == Enabled)
        {
            return;
        }
        await ChangeAsync(() => Api.SetRouterEnabledAsync(enabled), enabled ? "router_on" : "router_off");
    }

    [RelayCommand]
    public async Task AddRouteAsync()
    {
        var host = NewHost.Trim().ToLowerInvariant();
        if (host.Length == 0 || !ServerNames.Contains(NewServer))
        {
            Errors.Show("invalid_value", "");
            return;
        }
        var server = NewServer;
        await ChangeAsync(() => Api.SetRouterRouteAsync(host, server), "route");
        NewHost = "";
    }

    public async Task RemoveRouteAsync(string host, bool confirmed)
    {
        if (!confirmed || host.Length == 0)
        {
            return;
        }
        await ChangeAsync(() => Api.RemoveRouterRouteAsync(host), "route_removed");
    }

    public async Task SetDefaultAsync(string server)
    {
        if (!ServerNames.Contains(server) || server == DefaultServer)
        {
            return;
        }
        await ChangeAsync(() => Api.SetRouterDefaultAsync(server), "default");
    }

    public async Task EditAccessAsync(string kind, string action, string cidr)
    {
        cidr = cidr.Trim();
        if (kind is not ("allow" or "deny") || action is not ("add" or "remove") || cidr.Length == 0)
        {
            return;
        }
        await ChangeAsync(() => Api.EditRouterAccessAsync(kind, action, cidr), "access");
    }

    [RelayCommand]
    public async Task AddAccessAsync()
    {
        var cidr = NewCidr;
        await EditAccessAsync(AccessKind, "add", cidr);
        NewCidr = "";
    }
}

public sealed class SystemViewModel
{
    public SystemViewModel(IMcClient client, ErrorReporter errors, NotificationPrefs prefs)
    {
        Java = new JavaViewModel(client, errors);
        Devices = new DevicesViewModel(client, errors);
        Router = new RouterViewModel(client, errors);
        Update = new UpdateViewModel(client, errors);
        Doctor = new DoctorViewModel(client, errors);
        Notifications = prefs;
    }

    public JavaViewModel Java { get; }

    public DevicesViewModel Devices { get; }

    public RouterViewModel Router { get; }

    public UpdateViewModel Update { get; }

    public DoctorViewModel Doctor { get; }

    public NotificationPrefs Notifications { get; }

    public Task RefreshAsync() => Task.WhenAll(Java.RefreshAsync(), Devices.RefreshAsync(), Router.RefreshAsync(), Update.RefreshAsync());
}
