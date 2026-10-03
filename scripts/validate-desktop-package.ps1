$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sessionsRoot = Join-Path $projectRoot 'runtime/sessions'
$existingSessions = @(Get-ChildItem -LiteralPath $sessionsRoot -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$process = Start-Process -FilePath (Join-Path $projectRoot 'KnightAgent.exe') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
$window = $null
$runtimeProcess = $null
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $ready = $false
    while (-not $ready -and [DateTime]::UtcNow -lt $deadline) {
        if ($process.HasExited) { throw 'KnightAgent encerrou durante a inicializacao.' }
        $sessions = @(Get-ChildItem -LiteralPath $sessionsRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notin $existingSessions })
        foreach ($session in $sessions) {
            $logPath = Join-Path $session.FullName 'server.log'
            if (-not (Test-Path -LiteralPath $logPath)) { continue }
            $log = Get-Content -LiteralPath $logPath -Raw
            if ($log -match 'Listening on 127\.0\.0\.1:(\d+)' -and $log.Contains('Ollama cloud disabled: true')) {
                $localPort = $Matches[1]
                try {
                    $inventory = Invoke-RestMethod -Uri "http://127.0.0.1:$localPort/api/ps" -TimeoutSec 2
                    $ready = @($inventory.models).Count -gt 0
                } catch { $ready = $false }
            }
        }
        if (-not $ready) { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw 'Modelo local nao foi pre-carregado pelo executavel.' }
    $owned = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId = {0} AND Name = 'KnightAgent.exe'" -f $process.Id))
    if ($owned.Count -ne 1) { throw 'Processo da interface nao identificado.' }
    $window = [System.Diagnostics.Process]::GetProcessById($owned[0].ProcessId)
    $runtime = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId = {0} AND Name = 'ollama.exe'" -f $window.Id))
    if ($runtime.Count -ne 1) { throw 'Runtime privado nao identificado.' }
    $runtimeProcess = [System.Diagnostics.Process]::GetProcessById($runtime[0].ProcessId)
    if (-not $window.CloseMainWindow()) { throw 'A interface nao aceitou encerramento.' }
    if (-not $process.WaitForExit(10000)) { throw 'Aplicativo nao encerrou.' }
    if (-not $runtimeProcess.WaitForExit(5000)) { throw 'Runtime nao encerrou junto com o aplicativo.' }
    Write-Output 'Packaged desktop passed: window started, offline model preloaded, app and private runtime closed together.'
} finally {
    if ($window) {
        if (-not $window.HasExited) { $window.Kill(); $window.WaitForExit(5000) | Out-Null }
        $window.Dispose()
    }
    if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit(5000) | Out-Null }
    $process.Dispose()
    if ($runtimeProcess) { $runtimeProcess.Dispose() }
}
