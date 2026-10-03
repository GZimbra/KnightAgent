$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = Join-Path $projectRoot 'KnightAgentCopilot.exe'
$info.WorkingDirectory = $projectRoot
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardInput = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$bootloader = New-Object System.Diagnostics.Process
$bootloader.StartInfo = $info
$child = $null
try {
    if (-not $bootloader.Start()) { throw 'O auxiliar nao iniciou.' }
    # No request is submitted: the helper waits on stdin, with no login/network.
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not $child -and [DateTime]::UtcNow -lt $deadline) {
        $filter = "ParentProcessId = {0} AND Name = 'KnightAgentCopilot.exe'" -f $bootloader.Id
        $children = @(Get-CimInstance Win32_Process -Filter $filter)
        if ($children.Count -gt 0) {
            $child = [System.Diagnostics.Process]::GetProcessById($children[0].ProcessId)
        } else { Start-Sleep -Milliseconds 200 }
    }
    if (-not $child) { throw 'Processo interno do pacote nao encontrado.' }
    $bootloader.Kill()
    if (-not $bootloader.WaitForExit(5000)) { throw 'Bootloader nao encerrou.' }
    if (-not $child.WaitForExit(8000)) { throw 'Auxiliar permaneceu ativo apos cancelamento.' }
    Write-Output 'Packaged Copilot cancellation passed: owned bootloader and child stopped; no browser or login opened.'
} finally {
    if ($child) {
        if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit(5000) | Out-Null }
        $child.Dispose()
    }
    if (-not $bootloader.HasExited) { $bootloader.Kill(); $bootloader.WaitForExit(5000) | Out-Null }
    $bootloader.Dispose()
}
