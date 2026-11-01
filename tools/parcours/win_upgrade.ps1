param([string]$Setup)
. "$PSScriptRoot\lib.ps1"

$old = 'C:\mcm248'
$oldMc = { param($a) & python "$old\mc_cli.py" @a }.GetNewClosure()
$answers = "pv248`n`n`n1`n1.21.1`n25580`ny`nrcon-pass-248`n25581`n`nn`n"

Begin 'v2.4.8 install'
New-Item -ItemType Directory -Force $old | Out-Null
$zip = Join-Path $env:RUNNER_TEMP 'MCManager-248.zip'
Invoke-WebRequest 'https://github.com/scirr/MCMANAGER/releases/download/v2.4.8/MCManager.zip' -OutFile $zip
Expand-Archive $zip -DestinationPath $env:RUNNER_TEMP\x248 -Force
$src = Get-ChildItem $env:RUNNER_TEMP\x248 -Recurse -Filter install.bat | Select-Object -First 1
if (-not $src) { Fail 'install.bat not found in the 2.4.8 zip' }
Copy-Item "$($src.DirectoryName)\*" $old -Recurse -Force
Set-Content "$old\language.txt" 'en' -NoNewline
Push-Location $old
$out = cmd /c "install.bat < NUL 2>&1" | Out-String
$code = $LASTEXITCODE
Pop-Location
Write-Output $out
if ($code -ne 0) { Fail "install.bat exit code $code" ($out -split "`n" | Select-Object -Last 25 | Out-String) }
$svc = Get-Service MCManagerDaemon -ErrorAction SilentlyContinue
if (-not $svc) { Fail 'the 2.4.8 service was not created' ($out -split "`n" | Select-Object -Last 25 | Out-String) }
if (-not (Test-Path "$env:SystemRoot\System32\mc.bat")) { Fail 'mc.bat missing after the 2.4.8 install' }
End-Step

Begin 'v2.4.8 Vanilla 1.21.1'
Remove-Item Env:MCMANAGER_DATA_DIR -ErrorAction SilentlyContinue
Push-Location $old
$wrapper = "import getpass,runpy,sys;getpass.getpass=lambda p='',stream=None:input(p);sys.argv=['mc_cli.py','deploy'];runpy.run_path('mc_cli.py',run_name='__main__')"
$out = $answers | & python -c $wrapper 2>&1 | Out-String
Pop-Location
Write-Output $out
$reg = Get-Content "$old\servers.json" -Raw -ErrorAction SilentlyContinue
if (-not $reg -or $reg -notmatch 'pv248') { Fail 'the 2.4.8 deploy did not register the server' ($out -split "`n" | Select-Object -Last 25 | Out-String) }
Write-Output $reg
Start-And-Check $oldMc '2.4.8 server'
Stop-And-Check $oldMc
End-Step

Begin '3.0 over 2.4.8'
$log = Install-Setup $Setup $null
$root = Join-Path $env:ProgramFiles 'MCManager'
$mc = { param($a) & "$root\python\python.exe" "$root\core\mc_cli.py" @a }.GetNewClosure()
Wait-Service $log
$out = & $mc @('status', '--json') 2>&1 | Out-String
Write-Output $out
if ($out -notmatch 'pv248') {
  $dbg = "MCMANAGER_DATA_DIR=$env:MCMANAGER_DATA_DIR`n" + (Tail "$old\servers.json" 20) + "`n" + (Get-ChildItem "$env:ProgramData\MCManager" -Recurse -Depth 1 -ErrorAction SilentlyContinue | ForEach-Object FullName | Out-String)
  Fail 'the server created with 2.4.8 is not in the 3.0 registry' ($out + "`n" + $dbg)
}
Start-And-Check $mc '3.0 server'
Wait-Service $log
Stop-And-Check $mc
End-Step

Begin '3.0 uninstall'
Uninstall-Core $root
End-Step
