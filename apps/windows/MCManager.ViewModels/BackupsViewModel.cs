using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record BackupItem(string Id, string Date, string SizeText, string Origin, bool Encrypted);

public sealed partial class BackupsViewModel : ObservableObject
{
    private readonly IMcClient _client;
    private readonly ErrorReporter _errors;
    private readonly string _server;

    public BackupsViewModel(IMcClient client, ErrorReporter errors, string server)
    {
        _client = client;
        _errors = errors;
        _server = server;
    }

    public ObservableCollection<BackupItem> Items { get; } = new();

    public TimeSpan JobPollInterval { get; set; } = TimeSpan.FromSeconds(1);

    public int JobPollLimit { get; set; } = 3600;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanAct), nameof(IsEmpty))]
    private bool _isBusy;

    [ObservableProperty]
    private double _progress;

    [ObservableProperty]
    private string _lastDone = "";

    public bool CanAct => !IsBusy;

    public bool IsEmpty => Items.Count == 0;

    public static string FormatSize(long bytes)
    {
        double size = bytes;
        string[] units = { "B", "KB", "MB", "GB" };
        var unit = 0;
        while (size >= 1024 && unit < units.Length - 1)
        {
            size /= 1024;
            unit++;
        }
        return unit == 0 ? $"{(long)size} B" : $"{size.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture)} {units[unit]}";
    }

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await _errors.TryAsync(async () =>
        {
            var backups = await _client.ListBackupsAsync(_server);
            Items.Clear();
            foreach (var backup in backups)
            {
                Items.Add(new BackupItem(backup.Id, backup.Created.Replace('T', ' '), FormatSize(backup.Size), backup.Type, backup.Encrypted));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    [RelayCommand]
    public Task CreateAsync() => RunJobAsync("create", () => _client.CreateBackupAsync(_server));

    public Task RestoreAsync(string? id, bool confirmed)
    {
        if (!confirmed || string.IsNullOrEmpty(id))
        {
            return Task.CompletedTask;
        }
        return RunJobAsync("restore", () => _client.RestoreBackupAsync(_server, id, true));
    }

    private async Task RunJobAsync(string kind, Func<Task<Job>> start)
    {
        if (IsBusy)
        {
            return;
        }
        IsBusy = true;
        Progress = 0;
        LastDone = "";
        try
        {
            var ok = await _errors.TryAsync(async () =>
            {
                var job = await start();
                for (var i = 0; i < JobPollLimit && !job.IsFinished; i++)
                {
                    await Task.Delay(JobPollInterval);
                    job = await _client.GetJobAsync(job.Id);
                    Progress = Math.Clamp(job.Progress ?? 0, 0, 100);
                }
                if (!job.IsFinished)
                {
                    throw new ApiException("daemon_timeout", "", 0);
                }
                if (job.State != "succeeded" || job.Result is { Ok: false })
                {
                    throw new ApiException(job.Result?.Code ?? job.Code ?? "job_" + job.State, job.Result?.Message ?? "", 200);
                }
            });
            if (ok)
            {
                LastDone = kind;
            }
        }
        finally
        {
            IsBusy = false;
        }
        await RefreshAsync();
    }
}
