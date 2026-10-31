using System.Text.RegularExpressions;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class CreateServerViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Loaders = new[]
    {
        "Paper", "Purpur", "Spigot", "Folia", "Fabric", "Forge", "NeoForge", "Vanilla", "Velocity",
    };

    public const int LastStep = 2;

    private static readonly Regex RamPattern = new("^[1-9][0-9]*[GgMm]$");

    public CreateServerViewModel(IMcClient client, ErrorReporter errors)
        : base(client, errors, "")
    {
    }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanBack), nameof(CanNext), nameof(CanCreate), nameof(IsLastStep), nameof(IsFirstStep), nameof(IsMiddleStep))]
    private int _step;

    [ObservableProperty]
    private string _name = "";

    [ObservableProperty]
    private string _loader = "Paper";

    [ObservableProperty]
    private string _version = "";

    [ObservableProperty]
    private string _ram = "4G";

    [ObservableProperty]
    private string _port = "";

    [ObservableProperty]
    private string _rconPort = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanCreate))]
    private bool _acceptEula;

    [ObservableProperty]
    private string _createdName = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsModpack), nameof(ShowLoader))]
    private string _modpackSource = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasPackInfo))]
    private string _packInfo = "";

    public bool IsModpack => ModpackSource.Trim().Length > 0;

    public bool ShowLoader => !IsModpack;

    public bool HasPackInfo => IsModpack && PackInfo.Length > 0;

    partial void OnModpackSourceChanged(string value) => PackInfo = "";

    [RelayCommand]
    public async Task LookupModpackAsync()
    {
        var source = ModpackSource.Trim();
        if (source.Length == 0)
        {
            Errors.Show("source_required", "");
            return;
        }
        PackInfo = "";
        ModpackInfo? info = null;
        if (await WriteAsync(async () => info = await Api.GetModpackInfoAsync(source)) && info is not null)
        {
            PackInfo = string.Join(" - ", new[] { info.Title, info.Version, info.McVersion, info.Loader }.Where(s => !string.IsNullOrEmpty(s)));
        }
    }

    public bool CanBack => Step > 0 && !IsBusy;

    public bool CanNext => Step < LastStep;

    public bool IsLastStep => Step == LastStep;

    public bool IsFirstStep => Step == 0;

    public bool IsMiddleStep => Step == 1;

    public bool CanCreate => IsLastStep && AcceptEula && !IsBusy;

    public bool IsProxy => Loader == "Velocity";

    partial void OnLoaderChanged(string value) => OnPropertyChanged(nameof(IsProxy));

    protected override void BusyChanged()
    {
        OnPropertyChanged(nameof(CanBack));
        OnPropertyChanged(nameof(CanCreate));
    }

    private static bool PortOk(string text)
        => text.Length == 0 || (int.TryParse(text, out var port) && port is >= 1024 and <= 65535);

    private string? Validate(int step)
    {
        if (step == 0)
        {
            return Name.Trim().Length == 0 && !IsModpack ? "name_required" : null;
        }
        if (step == 1)
        {
            if (!RamPattern.IsMatch(Ram.Trim()))
            {
                return "invalid_ram";
            }
            if (!PortOk(Port.Trim()) || !PortOk(RconPort.Trim()))
            {
                return "invalid_port";
            }
        }
        return null;
    }

    [RelayCommand]
    public void Next()
    {
        if (Step >= LastStep)
        {
            return;
        }
        var problem = Validate(Step);
        if (problem is not null)
        {
            Errors.Show(problem, "");
            return;
        }
        Step++;
    }

    [RelayCommand]
    public void Back()
    {
        if (Step > 0)
        {
            Step--;
        }
    }

    [RelayCommand]
    public async Task CreateAsync()
    {
        if (!IsLastStep || !AcceptEula)
        {
            return;
        }
        for (var step = 0; step < LastStep; step++)
        {
            var problem = Validate(step);
            if (problem is not null)
            {
                Step = step;
                Errors.Show(problem, "");
                return;
            }
        }
        var version = Version.Trim();
        var port = Port.Trim();
        var rconPort = RconPort.Trim();
        if (IsModpack)
        {
            var pack = new ModpackInstallRequest
            {
                Source = ModpackSource.Trim(),
                AcceptEula = true,
                Name = Name.Trim().Length == 0 ? null : Name.Trim(),
                Ram = Ram.Trim().ToUpperInvariant(),
                Port = port.Length == 0 ? null : int.Parse(port),
                RconPort = rconPort.Length == 0 ? null : int.Parse(rconPort),
            };
            if (await RunJobAsync("create", () => Api.InstallModpackAsync(pack)))
            {
                CreatedName = LastJob?.Server ?? pack.Name ?? pack.Source;
            }
            return;
        }
        var request = new CreateServerRequest
        {
            Name = Name.Trim(),
            Loader = Loader,
            AcceptEula = true,
            Version = version.Length == 0 || IsProxy ? null : version,
            Ram = Ram.Trim().ToUpperInvariant(),
            Port = port.Length == 0 ? null : int.Parse(port),
            RconPort = rconPort.Length == 0 ? null : int.Parse(rconPort),
        };
        if (await RunJobAsync("create", () => Api.CreateServerAsync(request)))
        {
            CreatedName = request.Name;
        }
    }
}
