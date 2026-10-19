using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MCManager.Client;

namespace MCManager.ViewModels;

public sealed record DimensionItem(string Id, string SizeText, bool CanWrite = true);

public sealed partial class WorldViewModel : TabViewModel
{
    public WorldViewModel(IMcClient client, ErrorReporter errors, string server)
        : base(client, errors, server)
    {
    }

    public ObservableCollection<DimensionItem> Dimensions { get; } = new();

    protected override void ReadOnlyChanged() => Replace(Dimensions, item => item with { CanWrite = !IsReadOnly });

    [ObservableProperty]
    private string _totalSizeText = "-";

    [ObservableProperty]
    private string _pregenText = "";

    [ObservableProperty]
    private string _radiusText = "1000";

    [ObservableProperty]
    private string _centerText = "";

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await Errors.TryAsync(async () =>
        {
            var worlds = await Api.ListWorldsAsync(Server);
            Dimensions.Clear();
            foreach (var dimension in worlds.Dimensions)
            {
                Dimensions.Add(new DimensionItem(dimension.Id, BackupsViewModel.FormatSize(dimension.SizeBytes), !IsReadOnly));
            }
            TotalSizeText = BackupsViewModel.FormatSize(worlds.SizeBytes);
        });
        await RefreshPregenAsync();
    }

    [RelayCommand]
    public async Task RefreshPregenAsync()
    {
        try
        {
            PregenText = (await Api.GetPregenStatusAsync(Server)).Progress;
        }
        catch (ApiException ex) when (ex.Status is 409 or 503)
        {
            PregenText = "";
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Errors.Report(ex);
        }
    }

    [RelayCommand]
    public async Task StartPregenAsync()
    {
        if (!int.TryParse(RadiusText.Trim(), out var radius) || radius <= 0)
        {
            Errors.Show("invalid_radius", "");
            return;
        }
        var center = CenterText.Trim();
        var ok = await WriteAsync(async () =>
        {
            var started = await Api.StartPregenAsync(Server, radius, center.Length == 0 ? null : center);
            PregenText = started.Progress ?? "";
        });
        if (ok)
        {
            LastDone = "pregen";
        }
    }

    public async Task ResetAsync(string? dimension, bool confirmed)
    {
        if (!confirmed || string.IsNullOrEmpty(dimension))
        {
            return;
        }
        await RunJobAsync("reset", () => Api.ResetDimensionAsync(Server, dimension, true, dimension == "overworld"));
        await RefreshAsync();
    }
}
