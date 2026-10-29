using Microsoft.UI.Xaml.Data;

namespace MCManager.App;

public sealed partial class ChoiceLabelConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var text = value as string ?? "";
        return text.Length == 0 ? "" : Strings.Get("Choice_" + text.Replace('-', '_'), text);
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language) => value;
}
