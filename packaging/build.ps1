# Build every Windows release file into release\ (tests first):
#   TizoRecover-<v>-setup.exe     installer (per user, no admin), from the folder build
#   TizoRecover-<v>-portable.exe  one file, runs from anywhere
#   TizoRecover-<v>-x64.zip       the folder build (window + CLI)
#   latest.yml                    update feed (electron-builder format, read by the in-app updater)
# Usage (from the repository root):  powershell -File packaging\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

python tests\run_all.py
if ($LASTEXITCODE -ne 0) { throw "tests failed - not building" }

$v = (python packaging\release_tools.py version).Trim()
python packaging\release_tools.py version-info
python -m pip install --quiet --upgrade pyinstaller pywebview

Remove-Item -Recurse -Force dist, build, release -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\tizorecover.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (folder build) failed" }
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\portable packaging\portable.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (portable) failed" }

New-Item -ItemType Directory release | Out-Null
Copy-Item dist\TizoRecover-portable.exe "release\TizoRecover-$v-portable.exe"
Compress-Archive -Path dist\TizoRecover\* -DestinationPath "release\TizoRecover-$v-x64.zip"

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc /Q "/DAppVersion=$v" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

python packaging\release_tools.py feed "release\TizoRecover-$v-setup.exe" release\latest.yml

Get-ChildItem release | ForEach-Object { "{0,-34} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB) }
