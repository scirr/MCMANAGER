using MCManager.ViewModels;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MCManager.App.Views;

internal sealed class PairingDialog : ContentDialog
{
    private readonly PairingWizardViewModel _wizard;
    private readonly TextBlock _prompt = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBox _input = new();
    private readonly TextBlock _fingerprint = new()
    {
        IsTextSelectionEnabled = true,
        TextWrapping = TextWrapping.Wrap,
        FontFamily = new FontFamily("Consolas"),
        FontWeight = FontWeights.SemiBold,
    };
    private readonly TextBlock _error = new() { TextWrapping = TextWrapping.Wrap };
    private readonly ProgressRing _busy = new() { IsActive = false, Width = 20, Height = 20, HorizontalAlignment = HorizontalAlignment.Left };

    public PairingDialog(PairingWizardViewModel wizard)
    {
        _wizard = wizard;
        Title = Strings.Get("PairTitle", "Add a remote MC Manager");
        CloseButtonText = Strings.Get("PairCancel", "Cancel");
        DefaultButton = ContentDialogButton.Primary;
        var panel = new StackPanel { Spacing = 12, MinWidth = 420 };
        panel.Children.Add(_prompt);
        panel.Children.Add(_fingerprint);
        panel.Children.Add(_input);
        panel.Children.Add(_busy);
        panel.Children.Add(_error);
        Content = panel;
        PrimaryButtonClick += OnPrimary;
        SecondaryButtonClick += OnSecondary;
        Render();
    }

    private async void OnPrimary(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        var deferral = args.GetDeferral();
        try
        {
            _busy.IsActive = true;
            switch (_wizard.Step)
            {
                case PairingStep.Address:
                    _wizard.Address = _input.Text;
                    await _wizard.ProbeAsync();
                    break;
                case PairingStep.Confirm:
                    _wizard.ConfirmFingerprint();
                    break;
                case PairingStep.Code:
                    _wizard.Code = _input.Text.Trim();
                    _wizard.SubmitCode();
                    break;
                case PairingStep.Name:
                    _wizard.DeviceName = _input.Text;
                    await _wizard.FinishAsync();
                    break;
            }
            args.Cancel = _wizard.Step != PairingStep.Done;
            Render();
        }
        finally
        {
            _busy.IsActive = false;
            deferral.Complete();
        }
    }

    private void OnSecondary(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        _wizard.Reject();
        args.Cancel = true;
        Render();
    }

    private void Render()
    {
        var step = _wizard.Step;
        _prompt.Text = Strings.Get("PairStep_" + step);
        _fingerprint.Text = step == PairingStep.Confirm ? _wizard.Fingerprint : "";
        _fingerprint.Visibility = step == PairingStep.Confirm ? Visibility.Visible : Visibility.Collapsed;
        _input.Visibility = step == PairingStep.Confirm ? Visibility.Collapsed : Visibility.Visible;
        _input.Text = step switch
        {
            PairingStep.Address => _wizard.Address,
            PairingStep.Name => _wizard.DeviceName,
            _ => "",
        };
        _input.MaxLength = step == PairingStep.Code ? 8 : 256;
        SecondaryButtonText = step == PairingStep.Confirm ? Strings.Get("PairReject", "Reject") : "";
        PrimaryButtonText = Strings.Get(step switch
        {
            PairingStep.Confirm => "PairTrust",
            PairingStep.Name => "PairFinish",
            _ => "PairNext",
        });
        _error.Text = _wizard.ErrorCode.Length == 0 ? "" : Strings.Get("Error_" + _wizard.ErrorCode, _wizard.ErrorCode);
    }
}
