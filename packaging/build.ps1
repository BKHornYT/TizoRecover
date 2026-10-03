# Build both TizoRecover exes into dist\ and run the test suites first.
# Usage (from the repository root):  powershell -File packaging\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

python tests\run_all.py
if ($LASTEXITCODE -ne 0) { throw "tests failed - not building" }

python -m pip install --quiet --upgrade pyinstaller pywebview
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\tizorecover.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Get-ChildItem dist\TizoRecover*.exe | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    "{0}  {1:N1} MB  sha256 {2}" -f $_.Name, ($_.Length / 1MB), $hash
}
