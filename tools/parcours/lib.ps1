$ErrorActionPreference = 'Continue'
$script:Step = ''

function Fail([string]$message, [string]$detail = '') {
  $text = ($script:Step + ': ' + $message + "`n" + $detail) -replace '%', '%25' -replace "`r", '' -replace "`n", '%0A'
  Write-Output "::error title=Parcours $($script:Step)::$text"
  exit 1
}

function Begin([string]$name) { $script:Step = $name; Write-Output "::group::$name" }
function End-Step { Write-Output '::endgroup::' }

function Tail([string]$path, [int]$lines = 25) {
  if (Test-Path -LiteralPath $path) { (Get-Content -LiteralPath $path -Tail $lines) -join "`n" } else { "($path missing)" }
}

function Refresh-Env {
  $v = [Environment]::GetEnvironmentVariable('MCMANAGER_DATA_DIR', 'Machine')
  if ($v) { $env:MCMANAGER_DATA_DIR = $v } else { Remove-Item Env:MCMANAGER_DATA_DIR -ErrorAction SilentlyContinue }
}

function Server-Logs {
  $parts = @()
  $roots = @("$env:ProgramData\MCManager\Servers")
  if ($env:MCMANAGER_DATA_DIR) { $roots += (Join-Path $env:MCMANAGER_DATA_DIR 'Servers') }
  foreach ($r in $roots) {
    Get-ChildItem -Path $r -Filter latest.log -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
      $parts += "--- $($_.FullName)`n" + (Tail $_.FullName 20)
    }
  }
  $parts -join "`n"
}

function Wait-Rcon([scriptblock]$Mc, [int]$Seconds = 300) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  $out = ''
  while ((Get-Date) -lt $deadline) {
    $out = & $Mc @('rcon', 'list') 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $out -match 'players') { return $out }
    Start-Sleep -Seconds 5
  }
  Fail "RCON did not answer within ${Seconds}s" ($out + "`n" + (Server-Logs))
}

function Wait-Stopped([scriptblock]$Mc, [int]$Seconds = 90) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    $out = & $Mc @('rcon', 'list') 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { return }
    Start-Sleep -Seconds 3
  }
  Fail "the server is still answering RCON ${Seconds}s after mc stop" (Server-Logs)
}

function Start-And-Check([scriptblock]$Mc, [string]$what) {
  $out = & $Mc @('rcon', 'list') 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) {
    $out = & $Mc @('start') 2>&1 | Out-String
    Write-Output $out
  }
  $r = Wait-Rcon $Mc
  Write-Output "$what answers RCON: $r"
}

function Stop-And-Check([scriptblock]$Mc) {
  $out = & $Mc @('stop') 2>&1 | Out-String
  Write-Output $out
  Wait-Stopped $Mc
}

function Uninstall-Core([string]$root) {
  New-Item -ItemType Directory -Force "$env:ProgramData\MCManager\Servers\keep-me" | Out-Null
  $log = Join-Path $env:RUNNER_TEMP 'uninstall.log'
  & "$root\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART "/LOG=$log"
  foreach ($i in 1..60) { if (-not (Test-Path "$root\core")) { break }; Start-Sleep -Seconds 2 }
  if (Test-Path "$root\core") {
    $left = Get-ChildItem "$root\core" -Recurse -Force -ErrorAction SilentlyContinue | Select-Object -First 15 | ForEach-Object { $_.FullName }
    Fail 'uninstall left the core behind' ((Tail $log 30) + "`n--- left:`n" + ($left -join "`n"))
  }
  if (Get-Service MCManagerDaemon -ErrorAction SilentlyContinue) { Fail 'the service is still registered after uninstall' }
  if (Test-Path "$env:SystemRoot\System32\mc.bat") { Fail 'mc.bat is still there after uninstall' }
  if (-not (Test-Path "$env:ProgramData\MCManager\Servers\keep-me")) { Fail 'the uninstaller touched the servers folder' }
}

function Install-Setup([string]$setup, [string]$dir) {
  $log = Join-Path $env:RUNNER_TEMP 'install.log'
  $args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/LANG=en', "/LOG=$log")
  if ($dir) { $args += "/DIR=$dir" }
  $p = Start-Process -FilePath $setup -ArgumentList $args -Wait -PassThru
  if ($p.ExitCode -ne 0) { Fail "installer exit code $($p.ExitCode)" (Tail $log 30) }
  Refresh-Env
  return $log
}

function Wait-Service([string]$log) {
  $svc = $null
  foreach ($i in 1..30) {
    $svc = Get-Service MCManagerDaemon -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') { return }
    Start-Sleep -Seconds 2
  }
  Fail "MCManagerDaemon is not running ($($svc.Status))" (Tail $log 20)
}
