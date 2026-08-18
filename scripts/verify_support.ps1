$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到 .venv。请先在项目根目录执行：python -m venv .venv; .venv\Scripts\pip install -e '.[dev]'"
}

Push-Location $projectRoot
try {
    & $python -m pytest -q
    & $python -m ruff check src tests scripts
    & $python scripts\demo_support.py
}
finally {
    Pop-Location
}
