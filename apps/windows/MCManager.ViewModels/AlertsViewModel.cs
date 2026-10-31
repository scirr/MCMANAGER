using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed partial class AlertEventChoice : ObservableObject
{
    public AlertEventChoice(string key)
    {
        Key = key;
    }

    public string Key { get; }

    [ObservableProperty]
    private bool _isSelected;
}

public sealed record AlertItem(string Name, string Type, string Target, string Events, bool Legacy, bool CanWrite = true)
{
    public bool CanRemove => CanWrite && !Legacy;
}

public sealed partial class AlertsViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Types = new[] { "email", "telegram", "ntfy", "webhook", "discord" };

    public static readonly IReadOnlyList<string> EventKeys = new[]
    {
        "start", "stop", "crash", "crash_loop", "backup_failed", "update", "sleep", "wake",
    };

    private static readonly Dictionary<string, string[]> FieldsByType = new()
    {
        ["email"] = new[] { "host", "port", "user", "password", "sender", "to" },
        ["telegram"] = new[] { "token", "chat_id" },
        ["ntfy"] = new[] { "server", "topic", "token" },
        ["webhook"] = new[] { "url", "secret" },
        ["discord"] = new[] { "url" },
    };

    public AlertsViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
        foreach (var key in EventKeys)
        {
            EventChoices.Add(new AlertEventChoice(key));
        }
    }

    public ObservableCollection<AlertItem> Items { get; } = new();

    public ObservableCollection<AlertEventChoice> EventChoices { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    protected override void ReadOnlyChanged() => Replace(Items, item => item with { CanWrite = !IsReadOnly });

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowHost), nameof(ShowPort), nameof(ShowUser), nameof(ShowPassword), nameof(ShowSender),
        nameof(ShowTo), nameof(ShowToken), nameof(ShowChatId), nameof(ShowServer), nameof(ShowTopic), nameof(ShowUrl), nameof(ShowSecret))]
    private string _newType = "email";

    [ObservableProperty]
    private string _newName = "";

    [ObservableProperty]
    private string _newHost = "";

    [ObservableProperty]
    private string _newPort = "";

    [ObservableProperty]
    private string _newUser = "";

    [ObservableProperty]
    private string _newPassword = "";

    [ObservableProperty]
    private string _newSender = "";

    [ObservableProperty]
    private string _newTo = "";

    [ObservableProperty]
    private string _newToken = "";

    [ObservableProperty]
    private string _newChatId = "";

    [ObservableProperty]
    private string _newServer = "";

    [ObservableProperty]
    private string _newTopic = "";

    [ObservableProperty]
    private string _newUrl = "";

    [ObservableProperty]
    private string _newSecret = "";

    private bool Shows(string key) => FieldsByType.TryGetValue(NewType, out var keys) && keys.Contains(key);

    public bool ShowHost => Shows("host");

    public bool ShowPort => Shows("port");

    public bool ShowUser => Shows("user");

    public bool ShowPassword => Shows("password");

    public bool ShowSender => Shows("sender");

    public bool ShowTo => Shows("to");

    public bool ShowToken => Shows("token");

    public bool ShowChatId => Shows("chat_id");

    public bool ShowServer => Shows("server");

    public bool ShowTopic => Shows("topic");

    public bool ShowUrl => Shows("url");

    public bool ShowSecret => Shows("secret");

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await ReadAsync(async () =>
        {
            var list = await Api.ListAlertChannelsAsync(Server);
            Items.Clear();
            foreach (var channel in list.Channels)
            {
                Items.Add(new AlertItem(
                    channel.Name,
                    channel.Type,
                    channel.Topic ?? channel.Host ?? channel.ChatId ?? "",
                    string.Join(",", channel.Events),
                    channel.Legacy,
                    !IsReadOnly));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    private string? Field(string key, string value)
    {
        var text = value.Trim();
        return Shows(key) && text.Length > 0 ? text : null;
    }

    [RelayCommand]
    public async Task AddAsync()
    {
        if (!Types.Contains(NewType))
        {
            return;
        }
        int? port = null;
        var portText = Field("port", NewPort);
        if (portText is not null)
        {
            if (!int.TryParse(portText, out var parsed) || parsed is <= 0 or >= 65536)
            {
                Errors.Show("bad_port", "");
                return;
            }
            port = parsed;
        }
        var events = string.Join(",", EventChoices.Where(e => e.IsSelected).Select(e => e.Key));
        var name = NewName.Trim();
        var request = new AlertAddRequest
        {
            Type = NewType,
            Events = events.Length == 0 ? null : events,
            Name = name.Length == 0 ? null : name,
            Host = Field("host", NewHost),
            Port = port,
            User = Field("user", NewUser),
            Password = Field("password", NewPassword),
            Sender = Field("sender", NewSender),
            To = Field("to", NewTo),
            Token = Field("token", NewToken),
            ChatId = Field("chat_id", NewChatId),
            Server = Field("server", NewServer),
            Topic = Field("topic", NewTopic),
            Url = Field("url", NewUrl),
            Secret = Field("secret", NewSecret),
        };
        if (await WriteAsync(async () => await Api.AddAlertChannelAsync(Server, request)))
        {
            NewName = "";
            NewHost = "";
            NewPort = "";
            NewUser = "";
            NewPassword = "";
            NewSender = "";
            NewTo = "";
            NewToken = "";
            NewChatId = "";
            NewServer = "";
            NewTopic = "";
            NewUrl = "";
            NewSecret = "";
            LastDone = "added";
            await RefreshAsync();
        }
    }

    public async Task TestAsync(string? channel)
    {
        if (await WriteAsync(async () => await Api.TestAlertChannelsAsync(Server, channel)))
        {
            LastDone = "test";
        }
    }

    public async Task RemoveAsync(string channel, bool confirmed)
    {
        if (!confirmed || channel.Length == 0)
        {
            return;
        }
        if (await WriteAsync(async () => await Api.RemoveAlertChannelAsync(Server, channel)))
        {
            LastDone = "removed";
            await RefreshAsync();
        }
    }
}
