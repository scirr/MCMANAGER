using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class ServerDetailViewModel : ObservableObject, IDisposable
{
    private static readonly string[] StartableStates = { "stopped", "crashed", "stopped-by-user", "closed" };
    private static readonly string[] StoppableStates = { "running", "starting", "sleeping" };

    private readonly IMcClient _client;
    private readonly ErrorReporter _errors;

    public ServerDetailViewModel(IMcClient client, ErrorReporter errors, string name)
    {
        _client = client;
        _errors = errors;
        Name = name;
        Console = new ConsoleViewModel(client, errors, name);
        Players = new PlayersViewModel(client, errors, name);
        Backups = new BackupsViewModel(client, errors, name);
        Mods = new ModsViewModel(client, errors, name);
        Datapacks = new DatapacksViewModel(client, errors, name);
        World = new WorldViewModel(client, errors, name);
        Tasks = new TasksViewModel(client, errors, name);
        Settings = new SettingsViewModel(client, errors, name);
    }

    public string Name { get; }

    public ConsoleViewModel Console { get; }

    public PlayersViewModel Players { get; }

    public BackupsViewModel Backups { get; }

    public ModsViewModel Mods { get; }

    public DatapacksViewModel Datapacks { get; }

    public WorldViewModel World { get; }

    public TasksViewModel Tasks { get; }

    public SettingsViewModel Settings { get; }

    public TimeSpan JobPollInterval { get; set; } = TimeSpan.FromSeconds(1);

    public int JobPollLimit { get; set; } = 120;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanStart), nameof(CanStop), nameof(CanResume))]
    private string _state = "";

    [ObservableProperty]
    private string _version = "";

    [ObservableProperty]
    private string _ramText = "-";

    [ObservableProperty]
    private bool _isBusy;

    public bool CanStart => !IsBusy && StartableStates.Contains(State);

    public bool CanStop => !IsBusy && StoppableStates.Contains(State);

    public bool CanRestart => !IsBusy && State == "running";

    public bool CanResume => !IsBusy && State == "maintenance";

    partial void OnIsBusyChanged(bool value)
    {
        OnPropertyChanged(nameof(CanStart));
        OnPropertyChanged(nameof(CanStop));
        OnPropertyChanged(nameof(CanRestart));
        OnPropertyChanged(nameof(CanResume));
    }

    partial void OnStateChanged(string value) => OnPropertyChanged(nameof(CanRestart));

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await _errors.TryAsync(async () =>
        {
            var snapshot = await _client.GetServerAsync(Name);
            State = snapshot.Error is not null ? "error" : snapshot.State ?? "";
            Version = string.Join(" ", new[] { snapshot.Loader, snapshot.Version }.Where(s => !string.IsNullOrEmpty(s)));
            RamText = ServerItemViewModel.FormatRam(snapshot.RssKb);
        });
        await Players.LoadOnlineAsync();
    }

    [RelayCommand]
    public Task StartAsync() => ActAsync(() => _client.StartServerAsync(Name));

    [RelayCommand]
    public Task StopAsync() => ActAsync(() => _client.StopServerAsync(Name));

    [RelayCommand]
    public Task ResumeAsync() => ActAsync(() => _client.ResumeServerAsync(Name));

    [RelayCommand]
    public Task RestartAsync() => ActAsync(async () =>
    {
        var job = await _client.RestartServerAsync(Name);
        for (var i = 0; i < JobPollLimit && !job.IsFinished; i++)
        {
            await Task.Delay(JobPollInterval);
            job = await _client.GetJobAsync(job.Id);
        }
        if (job.State is "failed" or "cancelled")
        {
            throw new ApiException(job.Result?.Code ?? job.Code ?? "job_" + job.State, job.Result?.Message ?? "", 200);
        }
    });

    private async Task ActAsync(Func<Task> action)
    {
        IsBusy = true;
        try
        {
            await _errors.TryAsync(action);
            await RefreshAsync();
        }
        finally
        {
            IsBusy = false;
        }
    }

    public void Dispose() => Console.Stop();
}
