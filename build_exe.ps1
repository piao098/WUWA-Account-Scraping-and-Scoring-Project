$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$pyinstaller = $null

if (Get-Command uv -ErrorAction SilentlyContinue) {
  uv venv .venv
  uv pip install pyinstaller
  $pyinstaller = "uv run pyinstaller"
} else {
  Write-Host "uv was not found; using local .build_venv fallback for packaging only."
  python -m venv .build_venv
  .\.build_venv\Scripts\python.exe -m pip install --upgrade pip pyinstaller
  $pyinstaller = ".\.build_venv\Scripts\pyinstaller.exe"
}

Invoke-Expression "$pyinstaller --noconfirm --onefile --windowed --name `"pxb7_wuwa_push_app`" desktop_app.py"

$dist = Join-Path $PSScriptRoot "dist"
Copy-Item -Path (Join-Path $PSScriptRoot "configs") -Destination (Join-Path $dist "configs") -Recurse -Force
Copy-Item -Path (Join-Path $PSScriptRoot "notify_config.example.json") -Destination (Join-Path $dist "notify_config.example.json") -Force
New-Item -ItemType Directory -Path (Join-Path $dist "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dist "reports") -Force | Out-Null

Write-Host "Build complete: $PSScriptRoot\dist\pxb7_wuwa_push_app.exe"

<#
Equivalent command kept for reference:
pyinstaller `
  --noconfirm `
  --onefile `
  --windowed `
  --name "pxb7_wuwa_push_app" `
  desktop_app.py
#>
