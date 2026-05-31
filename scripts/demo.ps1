# Run from the repository root:
#   powershell -File scripts/demo.ps1
# Prefer cross-platform:
#   python scripts/demo.py

python (Join-Path $PSScriptRoot "demo.py")
exit $LASTEXITCODE
