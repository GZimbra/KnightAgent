# Run as administrator once, after building/copying the private runtime.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execute este script como Administrador para bloquear a rede do KnightAgent.'
}
$runtimeRoot = Join-Path $projectRoot 'runtime\ollama'
$programs = @((Join-Path $runtimeRoot 'ollama.exe'))
$application = Join-Path $projectRoot 'KnightAgent.exe'
if (Test-Path -LiteralPath $application -PathType Leaf) { $programs += $application }
$venvScripts = Join-Path $projectRoot '.venv\Scripts'
foreach ($name in @('python.exe', 'pythonw.exe', 'knightagent.exe', 'knightagent-gui.exe')) {
    $candidate = Join-Path $venvScripts $name
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $programs += $candidate }
}
$versionedExecutable = Join-Path $projectRoot 'KAgent V-0.1.exe'
if (Test-Path -LiteralPath $versionedExecutable -PathType Leaf) { $programs += $versionedExecutable }
$programs += @(Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File -Filter '*.exe' | Select-Object -ExpandProperty FullName)
$remoteAddresses = @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
$hash = [Security.Cryptography.SHA256]::Create()
foreach ($program in ($programs | Sort-Object -Unique)) {
    $resolved = (Resolve-Path -LiteralPath $program).Path
    if (-not $resolved.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Programa fora da pasta do KnightAgent.'
    }
    $digest = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($resolved.ToLowerInvariant()))).Replace('-', '').Substring(0, 20)
    $ruleName = 'KnightAgentOffline-' + $digest
    $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($existing) { Remove-NetFirewallRule -Name $ruleName }
    New-NetFirewallRule -Name $ruleName -DisplayName ('KnightAgent offline: ' + [IO.Path]::GetFileName($resolved)) -Group 'KnightAgent Offline' -Direction Outbound -Action Block -Enabled True -Profile Any -Program $resolved -RemoteAddress $remoteAddresses | Out-Null
}
$hash.Dispose()
Write-Output 'Rede externa bloqueada para o KnightAgent e seu runtime privado. Loopback preservado; Copilot independente.'
