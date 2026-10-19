using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record TaskItem(int Id, string Name, string Kind, string Cron, string Command, bool Enabled, string NextRun, string LastRun, string LastResult, string WarnText);

public sealed partial class TasksViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Actions = new[] { "restart", "backup", "command", "stop", "start" };

    public TasksViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
    }

    public ObservableCollection<TaskItem> Items { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    [ObservableProperty]
    private string _newName = "";

    [ObservableProperty]
    private string _newCron = "";

    [ObservableProperty]
    private string _newAction = "restart";

    [ObservableProperty]
    private string _newCommand = "";

    [ObservableProperty]
    private string _newWarn = "";

    public bool NeedsCommand => NewAction == "command";

    public bool AllowsWarn => NewAction is "restart" or "stop";

    partial void OnNewActionChanged(string value)
    {
        OnPropertyChanged(nameof(NeedsCommand));
        OnPropertyChanged(nameof(AllowsWarn));
    }

    private static string Stamp(string? value) => (value ?? "").Replace('T', ' ');

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await Errors.TryAsync(async () =>
        {
            var tasks = await Api.ListTasksAsync(Server);
            Items.Clear();
            foreach (var task in tasks)
            {
                Items.Add(new TaskItem(
                    task.Id,
                    task.Name,
                    task.Action,
                    task.Cron,
                    task.Command ?? "",
                    task.Enabled,
                    Stamp(task.NextRun),
                    Stamp(task.LastRun),
                    task.LastResult is null ? "" : task.LastResult.Ok ? "ok" : task.LastResult.Code,
                    string.Join(", ", task.Warn.Select(FormatWarn))));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    public static string FormatWarn(int seconds)
        => seconds % 60 == 0 ? (seconds / 60) + "m" : seconds + "s";

    [RelayCommand]
    public async Task CreateAsync()
    {
        var cron = NewCron.Trim();
        var command = NewCommand.Trim();
        if (cron.Length == 0)
        {
            Errors.Show("cron_required", "");
            return;
        }
        if (NeedsCommand && command.Length == 0)
        {
            Errors.Show("command_required", "");
            return;
        }
        var name = NewName.Trim();
        var warn = NewWarn.Trim();
        var request = new TaskCreateRequest
        {
            Cron = cron,
            Action = NewAction,
            Name = name.Length == 0 ? null : name,
            Command = NeedsCommand ? command : null,
            Warn = AllowsWarn && warn.Length > 0 ? warn : null,
        };
        if (await WriteAsync(async () => await Api.CreateTaskAsync(Server, request)))
        {
            NewName = "";
            NewCron = "";
            NewCommand = "";
            NewWarn = "";
            await RefreshAsync();
        }
    }

    public async Task SetEnabledAsync(int id, bool enabled)
    {
        if (await WriteAsync(async () => await Api.UpdateTaskAsync(Server, id, enabled)))
        {
            await RefreshAsync();
        }
    }

    public async Task DeleteAsync(int id, bool confirmed)
    {
        if (!confirmed)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.DeleteTaskAsync(Server, id)))
        {
            await RefreshAsync();
        }
    }

    public async Task RunAsync(int id)
    {
        await RunJobAsync("run", () => Api.RunTaskAsync(Server, id));
        await RefreshAsync();
    }
}
