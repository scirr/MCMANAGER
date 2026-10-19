using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MCManager.Client;

public interface IProfileProtector
{
    byte[] Protect(byte[] plain);

    byte[] Unprotect(byte[] protectedData);
}

[SupportedOSPlatform("windows")]
public sealed class DpapiProtector : IProfileProtector
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("MCManager.remotes.v1");

    public byte[] Protect(byte[] plain)
        => ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser);

    public byte[] Unprotect(byte[] protectedData)
        => ProtectedData.Unprotect(protectedData, Entropy, DataProtectionScope.CurrentUser);
}

public sealed class ProfileStore
{
    private readonly string _path;
    private readonly IProfileProtector _protector;

    public ProfileStore(string path, IProfileProtector protector)
    {
        _path = path;
        _protector = protector;
    }

    public static string DefaultPath()
        => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "MCManager", "remotes.dat");

    public IReadOnlyList<RemoteProfile> Load()
    {
        try
        {
            if (!File.Exists(_path))
            {
                return Array.Empty<RemoteProfile>();
            }
            var plain = _protector.Unprotect(File.ReadAllBytes(_path));
            return JsonSerializer.Deserialize(plain, McJson.Default.ProfileFile)?.Profiles ?? new List<RemoteProfile>();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or CryptographicException or JsonException)
        {
            return Array.Empty<RemoteProfile>();
        }
    }

    public void Save(IEnumerable<RemoteProfile> profiles)
    {
        var plain = JsonSerializer.SerializeToUtf8Bytes(new ProfileFile { Profiles = profiles.ToList() }, McJson.Default.ProfileFile);
        var data = _protector.Protect(plain);
        var folder = Path.GetDirectoryName(_path);
        if (!string.IsNullOrEmpty(folder))
        {
            Directory.CreateDirectory(folder);
        }
        var temp = _path + ".tmp";
        File.WriteAllBytes(temp, data);
        File.Move(temp, _path, true);
    }

    public void Add(RemoteProfile profile)
    {
        var all = Load().Where(p => p.Name != profile.Name).ToList();
        all.Add(profile);
        Save(all);
    }

    public void Remove(string name) => Save(Load().Where(p => p.Name != name));

    public string Export()
        => JsonSerializer.Serialize(Load().Select(p => p.Summary()).ToList(), McJson.Default.ListRemoteSummary);
}

public sealed record ProfileFile
{
    public List<RemoteProfile> Profiles { get; init; } = new();
}
