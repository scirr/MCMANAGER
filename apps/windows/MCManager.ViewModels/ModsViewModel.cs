using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record ModItem(string File, string Name, string Version, string Source, bool AddsBlocks, bool InModpack, bool CanWrite = true);

public sealed partial class ModsViewModel : TabViewModel
{
    public static readonly IReadOnlyList<string> Sources = new[] { "auto", "modrinth", "curseforge", "hangar" };

    public ModsViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
    }

    public ObservableCollection<ModItem> Items { get; } = new();

    public bool IsEmpty => Items.Count == 0;

    protected override void ReadOnlyChanged() => Replace(Items, item => item with { CanWrite = !IsReadOnly });

    [ObservableProperty]
    private string _newReference = "";

    [ObservableProperty]
    private string _selectedSource = "auto";

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await Errors.TryAsync(async () =>
        {
            var mods = await Api.ListModsAsync(Server);
            Items.Clear();
            foreach (var mod in mods)
            {
                Items.Add(new ModItem(
                    mod.File,
                    string.IsNullOrEmpty(mod.Name) ? mod.Id ?? mod.File : mod.Name,
                    mod.Version ?? "",
                    mod.Source ?? "",
                    mod.AddsBlocks,
                    mod.Modpack,
                    !IsReadOnly));
            }
            OnPropertyChanged(nameof(IsEmpty));
        });
    }

    [RelayCommand]
    public async Task AddAsync()
    {
        var reference = NewReference.Trim();
        if (reference.Length == 0)
        {
            return;
        }
        var source = SelectedSource is "" or "auto" ? null : SelectedSource;
        if (await RunJobAsync("add", () => Api.AddModAsync(Server, reference, source)))
        {
            NewReference = "";
            RestartRequired = true;
        }
        await RefreshAsync();
    }

    [RelayCommand]
    public async Task UpdateAllAsync()
    {
        if (await RunJobAsync("update", () => Api.UpdateModsAsync(Server)))
        {
            RestartRequired = true;
        }
        await RefreshAsync();
    }

    public async Task RemoveAsync(string? file, bool confirmed)
    {
        if (!confirmed || string.IsNullOrEmpty(file) || IsBusy)
        {
            return;
        }
        var item = Items.FirstOrDefault(m => m.File == file);
        var ok = await WriteAsync(async () =>
        {
            var removed = await Api.RemoveModAsync(Server, file, item?.AddsBlocks ?? false);
            if (removed.RestartRequired)
            {
                RestartRequired = true;
            }
        });
        if (ok)
        {
            LastDone = "remove";
            await RefreshAsync();
        }
    }
}
