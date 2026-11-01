# Crea un acceso directo "Capturas" en el Escritorio de Windows.
# Usa pythonw.exe para que no aparezca ninguna ventana de consola.
#
# Uso:  powershell -ExecutionPolicy Bypass -File install-windows.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$pyw = Join-Path $here ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) {
    Write-Host "[1/2] Creando entorno virtual e instalando dependencias..."
    python -m venv .venv
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt | Out-Null
}

Write-Host "[2/2] Creando acceso directo..."
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "Capturas.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $pyw
$lnk.Arguments = '"' + (Join-Path $here "capturas.py") + '"'
$lnk.WorkingDirectory = $here
$lnk.IconLocation = Join-Path $here "icon.ico"
$lnk.Description = "Capturas de pantalla: completa o recortada, guardado automatico"
$lnk.Save()

Write-Host ""
Write-Host "LISTO: $lnkPath"
Write-Host "Doble clic en 'Capturas' del Escritorio para abrir la app."
