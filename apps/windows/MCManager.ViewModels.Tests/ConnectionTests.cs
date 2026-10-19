using MCManager.Client;
using Xunit;

namespace MCManager.ViewModels.Tests;

public sealed class ConnectionTests : IDisposable
{
    private readonly string _folder = Path.Combine(Path.GetTempPath(), "mcmvm-" + Guid.NewGuid().ToString("N"));
    private readonly FakePairing _pairing = new();
    private readonly FakeClient _local = new();
    private readonly List<RemoteProfile> _remoteCalls = new();

    public void Dispose()
    {
        if (Directory.Exists(_folder))
        {
            Directory.Delete(_folder, true);
        }
    }

    private ConnectionViewModel Create()
        => new(new ProfileStore(Path.Combine(_folder, "r.dat"), new TestProtector()), _pairing, "This machine",
            () => _local, p => { _remoteCalls.Add(p); return new FakeClient(); });

    private static async Task Complete(PairingWizardViewModel wizard, string code = "48201937")
    {
        wizard.Address = "srv.example:8765";
        await wizard.ProbeAsync();
        wizard.ConfirmFingerprint();
        wizard.Code = code;
        wizard.SubmitCode();
        await wizard.FinishAsync();
    }

    [Fact]
    public async Task Wizard_shows_fingerprint_then_pairs_and_stores_the_profile()
    {
        var connection = Create();
        var wizard = new PairingWizardViewModel(connection, "PC");

        wizard.Address = "srv.example:8765";
        await wizard.ProbeAsync();
        Assert.Equal(PairingStep.Confirm, wizard.Step);
        Assert.Equal(FakePairing.Pin, wizard.Fingerprint);
        Assert.DoesNotContain(_pairing.Calls, c => c.StartsWith("pair"));

        wizard.ConfirmFingerprint();
        wizard.Code = "48201937";
        wizard.SubmitCode();
        wizard.DeviceName = "Phone";
        await wizard.FinishAsync();

        Assert.Equal(PairingStep.Done, wizard.Step);
        Assert.Contains($"pair {FakePairing.Pin} 48201937 Phone", _pairing.Calls);
        Assert.Equal(new[] { "This machine", "Phone" }, connection.Targets.Select(t => t.Name));
        Assert.Equal("Phone", connection.Selected.Name);
    }

    [Fact]
    public async Task Wizard_cannot_skip_the_fingerprint_confirmation()
    {
        var wizard = new PairingWizardViewModel(Create(), "PC");
        wizard.Address = "srv.example:8765";
        await wizard.ProbeAsync();

        wizard.Code = "48201937";
        wizard.SubmitCode();

        Assert.NotEqual(PairingStep.Name, wizard.Step);
        wizard.Reject();
        Assert.Equal(PairingStep.Address, wizard.Step);
        Assert.Equal("", wizard.Fingerprint);
    }

    [Fact]
    public async Task Wizard_rejects_bad_address_and_malformed_code()
    {
        var wizard = new PairingWizardViewModel(Create(), "PC");
        wizard.Address = "nonsense";
        await wizard.ProbeAsync();
        Assert.Equal("bad_address", wizard.ErrorCode);
        Assert.Empty(_pairing.Calls);

        wizard.Address = "srv:1";
        await wizard.ProbeAsync();
        wizard.ConfirmFingerprint();
        wizard.Code = "1234";
        wizard.SubmitCode();
        Assert.Equal("bad_pair_code", wizard.ErrorCode);
        Assert.Equal(PairingStep.Code, wizard.Step);
    }

    [Fact]
    public async Task Wrong_code_returns_to_the_code_step_and_stores_nothing()
    {
        _pairing.Failure = new ApiException("bad_pair_code", "", 422);
        var connection = Create();
        var wizard = new PairingWizardViewModel(connection, "PC");

        await Complete(wizard);

        Assert.Equal(PairingStep.Code, wizard.Step);
        Assert.Equal("bad_pair_code", wizard.ErrorCode);
        Assert.Equal("", wizard.Code);
        Assert.Single(connection.Targets);
    }

    [Fact]
    public async Task Selection_chooses_this_machine_or_a_remote_profile()
    {
        var connection = Create();
        await Complete(new PairingWizardViewModel(connection, "PC"));

        Assert.NotNull(connection.CreateClient());
        Assert.Single(_remoteCalls);
        Assert.Equal("mcm_tok", _remoteCalls[0].Token);

        connection.Selected = connection.LocalTarget;
        Assert.Same(_local, connection.CreateClient());
        Assert.Single(_remoteCalls);
    }

    [Fact]
    public async Task Removing_a_profile_goes_back_to_this_machine()
    {
        var connection = Create();
        await Complete(new PairingWizardViewModel(connection, "PC"));

        connection.RemoveSelected();

        Assert.Single(connection.Targets);
        Assert.True(connection.Selected.IsLocal);
        Assert.DoesNotContain("mcm_tok", connection.Selected.ToString());
    }
}
