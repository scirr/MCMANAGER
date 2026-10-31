using System.Text.Json;

namespace MCManager.App;

internal static class NotificationStore
{
    private static string FilePath()
        => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "MCManager", "notifications.json");

    public static Dictionary<string, bool>? Load()
    {
        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, bool>>(File.ReadAllText(FilePath()));
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static void Save(IReadOnlyDictionary<string, bool> values)
    {
        try
        {
            var path = FilePath();
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(values));
        }
        catch (Exception)
        {
        }
    }
}
