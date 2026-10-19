using CommunityToolkit.Mvvm.ComponentModel;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class ErrorReporter : ObservableObject
{
    [ObservableProperty]
    private string _message = "";

    [ObservableProperty]
    private string _code = "";

    [ObservableProperty]
    private bool _isOpen;

    public void Report(Exception exception)
    {
        if (exception is OperationCanceledException)
        {
            return;
        }
        if (exception is ApiException api)
        {
            Show(api.Code, api.Message);
        }
        else
        {
            Show("error", exception.Message);
        }
    }

    public void Show(string code, string message)
    {
        Code = code;
        Message = message;
        IsOpen = true;
    }

    public void Clear()
    {
        IsOpen = false;
        Message = "";
        Code = "";
    }

    public async Task<bool> TryAsync(Func<Task> action)
    {
        try
        {
            await action();
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Report(ex);
            return false;
        }
    }
}
