$ErrorActionPreference = "Stop"

$projectPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $projectPython) { $projectPython } else { "python" }

function Invoke-Python {
  & $python @args
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed with exit code $LASTEXITCODE"
  }
}

& $python -c "import copilot, PyInstaller"
if ($LASTEXITCODE -ne 0) {
  Invoke-Python -m pip install --require-hashes -r requirements.lock
  Invoke-Python -m pip install --no-deps -e .
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$safeRoot = $projectRoot.Replace("\", "/")
$commitOutput = & git -c "safe.directory=$safeRoot" rev-parse --short=12 HEAD
$commit = if ($LASTEXITCODE -eq 0) { ($commitOutput | Select-Object -First 1).Trim() } else { "" }
if (-not $commit) { $commit = "unknown" }
$runtimeHook = Join-Path $PSScriptRoot "..\build\runtime_build_info.py"
New-Item -ItemType Directory -Force -Path (Split-Path $runtimeHook) | Out-Null
Set-Content -LiteralPath $runtimeHook -Encoding UTF8 -Value @"
import os
os.environ["GITHUB_MEMBER_ACTIVITY_BUILD_COMMIT"] = "$commit"
"@
Invoke-Python -m copilot download-runtime
Invoke-Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name github-member-activity `
  --collect-all copilot `
  --add-data "$projectRoot\src\github_team_stats\presentation\web\static;github_team_stats\presentation\web\static" `
  --runtime-hook $runtimeHook `
  --paths src `
  src/github_team_stats/__main__.py

$exe = Join-Path $PSScriptRoot "..\dist\github-member-activity.exe"
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
$hashFile = "$exe.sha256"
Set-Content -LiteralPath $hashFile -Encoding ASCII -Value "$hash  github-member-activity.exe"
Write-Host "Built dist/github-member-activity.exe"
Write-Host "SHA256: $hash"
Write-Host "Checksum: dist/github-member-activity.exe.sha256"
