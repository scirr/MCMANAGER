param([string]$Setup)
. "$PSScriptRoot\lib.ps1"

$dir = 'C:\Prog M' + [char]0x00EE + 'ne ' + [char]0x00C9 + 't' + [char]0x00E9 + '\MC Manager'
Begin 'fresh 3.0 install'
$log = Install-Setup $Setup $dir
if (-not (Test-Path -LiteralPath "$dir\core\mc_cli.py")) { Fail "not installed in $dir" (Tail $log 25) }
Wait-Service $log
$mc = { param($a) & "$dir\python\python.exe" "$dir\core\mc_cli.py" @a }.GetNewClosure()
$out = cmd /c "mc version 2>&1" | Out-String
if ($LASTEXITCODE -ne 0) { Fail 'the global mc command failed' $out }
End-Step

foreach ($t in @(@('Paper', 'pap', 25590), @('Fabric', 'fab', 25592))) {
  Begin "$($t[0]) 1.21.1"
  $out = & $mc @('deploy', '--name', "t-$($t[1])", '--loader', $t[0], '--version', '1.21.1', '--port', "$($t[2])", '--rcon-port', "$($t[2] + 1)", '--ram', '1G', '--accept-eula', '--yes') 2>&1 | Out-String
  Write-Output $out
  if ($LASTEXITCODE -ne 0) { Fail "deploy $($t[0]) exit code $LASTEXITCODE" ($out -split "`n" | Select-Object -Last 25 | Out-String) }
  & $mc @('use', "t-$($t[1])") 2>&1 | Out-Null
  Start-And-Check $mc $t[0]
  Stop-And-Check $mc
  End-Step
}

Begin 'fresh uninstall'
Uninstall-Core $dir
End-Step
