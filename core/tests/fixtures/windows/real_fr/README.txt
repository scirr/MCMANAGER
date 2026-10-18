Real command outputs.
Provenance: Windows 11 fr-FR, PowerShell 5.1, relevé le 2026-10-18.

netstat, sc and tasklist files are cp850 (OEM console code page 850).
netsh files come in two variants, cp850 and utf-8, with real U+00A0 before the colons.
PowerShell files are UTF-8 (ConvertTo-Json of Windows PowerShell 5.1: enumerations are numbers).
Third-party rule names and the remote IP are anonymised.
tasklist memory uses U+00A0 as the thousands separator.
