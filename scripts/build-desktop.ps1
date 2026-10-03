$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $iconPath = Join-Path $projectRoot 'src/knightagent/gui/assets/knight-agent.ico'
    $sourcePath = Join-Path $projectRoot 'src'
    # Hidden by the parent when used. A separate executable keeps Microsoft
    # traffic outside the main application/Ollama outbound firewall block.
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onefile --console --name KnightAgentCopilot --paths $sourcePath --distpath . --workpath build/copilot --specpath build 'scripts/copilot-entry.py'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar KnightAgentCopilot.exe.' }
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onefile --windowed --name KnightAgent --paths $sourcePath --collect-data knightagent.gui --icon $iconPath --distpath . --workpath build/desktop --specpath build 'scripts/desktop-entry.py'
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar KnightAgent.exe.' }
} finally { Pop-Location }
