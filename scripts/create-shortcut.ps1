# Recreate the local application shortcut after moving the project directory.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$executablePath = Join-Path $projectRoot 'KnightAgent.exe'
$iconPath = Join-Path $projectRoot 'src\knightagent\gui\assets\knight-agent.ico'
$configPath = Join-Path $projectRoot 'config.yaml'
if (-not (Test-Path -LiteralPath $pythonPath) -and -not (Test-Path -LiteralPath $executablePath)) {
    throw 'Ambiente virtual ausente. Instale o aplicativo conforme o README.'
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $projectRoot 'Knight Agent.lnk'))
if (Test-Path -LiteralPath $executablePath) {
    $shortcut.TargetPath = $executablePath
    $shortcut.Arguments = '--config "' + $configPath + '"'
} else {
    $shortcut.TargetPath = $pythonPath
    $shortcut.Arguments = '-m knightagent.gui.main --config "' + $configPath + '"'
}
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = 'Knight Agent - Powered By Digitec'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Output 'Atalho Knight Agent.lnk criado com o ícone do aplicativo.'
