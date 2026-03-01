# start_live_scanner.ps1 — Start the live scanner daemon
$env:PYTHONIOENCODING = "utf-8"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir
python tracker/live_scanner.py
