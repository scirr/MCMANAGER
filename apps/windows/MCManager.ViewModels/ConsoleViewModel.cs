using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class ConsoleViewModel : ObservableObject
{
    public const int MaxLines = 1000;

    private readonly IMcClient _client;
    private readonly ErrorReporter _errors;
    private readonly string _server;
    private CancellationTokenSource? _cts;

    public ConsoleViewModel(IMcClient client, ErrorReporter errors, string server)
    {
        _client = client;
        _errors = errors;
        _server = server;
    }

    public ObservableCollection<string> Lines { get; } = new();

    public Task Completion { get; private set; } = Task.CompletedTask;

    [ObservableProperty]
    private string _commandText = "";

    [ObservableProperty]
    private bool _isStreaming;

    public void Start()
    {
        Stop();
        var cts = new CancellationTokenSource();
        _cts = cts;
        Completion = RunAsync(cts.Token);
    }

    public void Stop()
    {
        _cts?.Cancel();
        _cts = null;
    }

    private async Task RunAsync(CancellationToken ct)
    {
        IsStreaming = true;
        try
        {
            await foreach (var item in _client.StreamConsoleAsync(_server, 200, ct))
            {
                if (item.Name is "line" or "message")
                {
                    Append(item.Data);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _errors.Report(ex);
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            IsStreaming = false;
        }
    }

    [RelayCommand]
    public async Task SendAsync()
    {
        var command = CommandText.Trim();
        if (command.Length == 0)
        {
            return;
        }
        CommandText = "";
        await _errors.TryAsync(async () =>
        {
            Append("> " + command);
            var reply = await _client.SendConsoleCommandAsync(_server, command);
            if (!string.IsNullOrWhiteSpace(reply.Output))
            {
                foreach (var line in reply.Output.Split('\n'))
                {
                    Append(line.TrimEnd('\r'));
                }
            }
        });
    }

    private void Append(string line)
    {
        Lines.Add(line);
        while (Lines.Count > MaxLines)
        {
            Lines.RemoveAt(0);
        }
    }
}
