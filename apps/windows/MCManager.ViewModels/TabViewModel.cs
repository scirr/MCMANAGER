using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using MCManager.Client;

namespace MCManager.ViewModels;

public abstract partial class TabViewModel : ObservableObject
{
    protected TabViewModel(IMcClient client, ErrorReporter errors, string server)
    {
        Api = client;
        Errors = errors;
        Server = server;
    }

    protected IMcClient Api { get; }

    protected ErrorReporter Errors { get; }

    protected string Server { get; }

    public TimeSpan JobPollInterval { get; set; } = TimeSpan.FromSeconds(1);

    public int JobPollLimit { get; set; } = 3600;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanAct))]
    private bool _isBusy;

    [ObservableProperty]
    private double _progress;

    [ObservableProperty]
    private string _lastDone = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanWrite), nameof(CanAct))]
    private bool _isReadOnly;

    [ObservableProperty]
    private bool _restartRequired;

    partial void OnIsBusyChanged(bool value) => BusyChanged();

    partial void OnIsReadOnlyChanged(bool value) => ReadOnlyChanged();

    protected virtual void ReadOnlyChanged()
    {
    }

    protected static void Replace<T>(ObservableCollection<T> items, Func<T, T> change)
    {
        for (var i = 0; i < items.Count; i++)
        {
            items[i] = change(items[i]);
        }
    }

    protected virtual void BusyChanged()
    {
    }

    public bool CanAct => !IsBusy && !IsReadOnly;

    public bool CanWrite => !IsReadOnly;

    protected async Task<bool> WriteAsync(Func<Task> action)
    {
        return await Errors.TryAsync(async () =>
        {
            try
            {
                await action();
            }
            catch (ApiException ex) when (ex.Status == 403)
            {
                IsReadOnly = true;
                throw;
            }
        });
    }

    protected Task<bool> ReadAsync(Func<Task> action) => WriteAsync(action);

    public Job? LastJob { get; private set; }

    protected async Task<bool> RunJobAsync(string kind, Func<Task<Job>> start)
    {
        if (IsBusy)
        {
            return false;
        }
        IsBusy = true;
        Progress = 0;
        LastDone = "";
        LastJob = null;
        var ok = false;
        try
        {
            ok = await WriteAsync(async () =>
            {
                var job = await start();
                for (var i = 0; i < JobPollLimit && !job.IsFinished; i++)
                {
                    await Task.Delay(JobPollInterval);
                    job = await Api.GetJobAsync(job.Id);
                    Progress = Math.Clamp(job.Progress ?? 0, 0, 100);
                }
                if (!job.IsFinished)
                {
                    throw new ApiException("daemon_timeout", "", 0);
                }
                LastJob = job;
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
        return ok;
    }
}
