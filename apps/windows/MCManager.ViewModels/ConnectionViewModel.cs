using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record ConnectionTarget(string Name, RemoteProfile? Profile)
{
    public bool IsLocal => Profile is null;

    public override string ToString() => Name;
}

public sealed partial class ConnectionViewModel : ObservableObject
{
    private readonly ProfileStore _store;
    private readonly Func<IMcClient?> _local;
    private readonly Func<RemoteProfile, IMcClient> _remote;

    public ConnectionViewModel(
        ProfileStore store,
        IPairingClient pairing,
        string localName,
        Func<IMcClient?> local,
        Func<RemoteProfile, IMcClient>? remote = null)
    {
        _store = store;
        Pairing = pairing;
        _local = local;
        _remote = remote ?? (profile => RemoteTransport.Create(profile));
        LocalTarget = new ConnectionTarget(localName, null);
        Selected = LocalTarget;
        Reload();
    }

    public IPairingClient Pairing { get; }

    public ConnectionTarget LocalTarget { get; }

    public ObservableCollection<ConnectionTarget> Targets { get; } = new();

    [ObservableProperty]
    private ConnectionTarget _selected = new("", null);

    public event Action? Changed;

    public void Reload()
    {
        var current = Selected?.Profile?.Name;
        Targets.Clear();
        Targets.Add(LocalTarget);
        foreach (var profile in _store.Load())
        {
            Targets.Add(new ConnectionTarget(profile.Name, profile));
        }
        Selected = Targets.FirstOrDefault(t => t.Profile?.Name == current) ?? LocalTarget;
    }

    public IMcClient? CreateClient()
        => Selected.Profile is null ? _local() : _remote(Selected.Profile);

    public void Apply() => Changed?.Invoke();

    public void AddProfile(RemoteProfile profile)
    {
        _store.Add(profile);
        Reload();
        Selected = Targets.First(t => t.Profile?.Name == profile.Name);
    }

    public void RemoveSelected()
    {
        if (Selected.Profile is null)
        {
            return;
        }
        _store.Remove(Selected.Profile.Name);
        Reload();
        Selected = LocalTarget;
    }
}

public enum PairingStep
{
    Address,
    Confirm,
    Code,
    Name,
    Done,
}

public sealed partial class PairingWizardViewModel : ObservableObject
{
    private readonly ConnectionViewModel _connection;
    private string _host = "";
    private int _port;

    public PairingWizardViewModel(ConnectionViewModel connection, string defaultName)
    {
        _connection = connection;
        DeviceName = defaultName;
    }

    [ObservableProperty]
    private PairingStep _step = PairingStep.Address;

    [ObservableProperty]
    private string _address = "";

    [ObservableProperty]
    private string _fingerprint = "";

    [ObservableProperty]
    private string _code = "";

    [ObservableProperty]
    private string _deviceName = "";

    [ObservableProperty]
    private string _errorCode = "";

    [ObservableProperty]
    private bool _isBusy;

    public static bool IsCode(string? value) => value is { Length: 8 } && value.All(c => c is >= '0' and <= '9');

    public async Task ProbeAsync(CancellationToken ct = default)
    {
        ErrorCode = "";
        if (!HostPort.TryParse(Address, out _host, out _port))
        {
            ErrorCode = "bad_address";
            return;
        }
        await RunAsync(async () =>
        {
            Fingerprint = await _connection.Pairing.FetchFingerprintAsync(_host, _port, ct);
            Step = PairingStep.Confirm;
        });
    }

    public void ConfirmFingerprint()
    {
        if (Step == PairingStep.Confirm && Fingerprint.Length > 0)
        {
            Step = PairingStep.Code;
        }
    }

    public void Reject()
    {
        Fingerprint = "";
        Code = "";
        Step = PairingStep.Address;
    }

    public void SubmitCode()
    {
        ErrorCode = "";
        if (Step != PairingStep.Code)
        {
            return;
        }
        if (!IsCode(Code))
        {
            ErrorCode = "bad_pair_code";
            return;
        }
        Step = PairingStep.Name;
    }

    public async Task FinishAsync(CancellationToken ct = default)
    {
        ErrorCode = "";
        var name = DeviceName.Trim();
        if (name.Length == 0)
        {
            ErrorCode = "bad_name";
            return;
        }
        await RunAsync(async () =>
        {
            var profile = await _connection.Pairing.PairAsync(_host, _port, Fingerprint, Code, name, ct);
            _connection.AddProfile(profile);
            Code = "";
            Step = PairingStep.Done;
        }, onApiError: () =>
        {
            Code = "";
            Step = PairingStep.Code;
        });
    }

    private async Task RunAsync(Func<Task> action, Action? onApiError = null)
    {
        IsBusy = true;
        try
        {
            await action();
        }
        catch (ApiException ex)
        {
            ErrorCode = ex.Code;
            onApiError?.Invoke();
        }
        finally
        {
            IsBusy = false;
        }
    }
}
