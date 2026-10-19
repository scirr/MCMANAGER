using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record BackupItem(string Id, string Date, string SizeText, string Origin, bool Encrypted, bool CanWrite = true);

public sealed partial class BackupsViewModel : TabViewModel
{
    public BackupsViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
    }

    public ObservableCollection<BackupItem> Items { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    protected override void ReadOnlyChanged() => Replace(Items, item => item with { CanWrite = !IsReadOnly });

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
        await Errors.TryAsync(async () =>
        {
            var backups = await Api.ListBackupsAsync(Server);
            Items.Clear();
            foreach (var backup in backups)
            {
                Items.Add(new BackupItem(backup.Id, backup.Created.Replace('T', ' '), FormatSize(backup.Size), backup.Type, backup.Encrypted, !IsReadOnly));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    [RelayCommand]
    public Task CreateAsync() => RunAndRefreshAsync("create", () => Api.CreateBackupAsync(Server));

    public Task RestoreAsync(string? id, bool confirmed)
    {
        if (!confirmed || string.IsNullOrEmpty(id))
        {
            return Task.CompletedTask;
        }
        return RunAndRefreshAsync("restore", () => Api.RestoreBackupAsync(Server, id, true));
    }

    private async Task RunAndRefreshAsync(string kind, Func<Task<Job>> start)
    {
        if (IsBusy)
        {
            return;
        }
        await RunJobAsync(kind, start);
        await RefreshAsync();
    }
}
