namespace MCManager.Client;

public sealed class ApiException : Exception
{
    public ApiException(string code, string message, int status)
        : base(string.IsNullOrEmpty(message) ? code : message)
    {
        Code = code;
        Status = status;
        DaemonMessage = message;
    }

    public string Code { get; }

    public int Status { get; }

    public string DaemonMessage { get; }
}
