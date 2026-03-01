# watchdog.ps1 — Hype Scout v2 Process Watchdog
# Keeps scanner, poster, and telegram bot alive.
# Run this via Task Scheduler: every 2 minutes, "Run whether user is logged in or not"

$ProjectDir = "C:\Users\kanaw\.openclaw\workspace\ventures\hype-scout-v2"
$Python = "C:\Users\kanaw\AppData\Local\Python\pythoncore-3.14-64\python.exe"

function Is-AliveViaPid($pidFile) {
    $lockPath = Join-Path $ProjectDir $pidFile
    if (-not (Test-Path $lockPath)) { return $false }
    $storedPid = Get-Content $lockPath -ErrorAction SilentlyContinue
    if (-not $storedPid) { return $false }
    $proc = Get-Process -Id ([int]$storedPid) -ErrorAction SilentlyContinue
    return ($proc -ne $null)
}

function Start-Component($name, $script, $args = "") {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting $name..."
    $env:PYTHONIOENCODING = "utf-8"
    if ($args) {
        Start-Process $Python -ArgumentList "$script $args" `
            -WorkingDirectory $ProjectDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput "$ProjectDir\logs\$name.log" `
            -RedirectStandardError "$ProjectDir\logs\${name}_err.log"
    } else {
        Start-Process $Python -ArgumentList $script `
            -WorkingDirectory $ProjectDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput "$ProjectDir\logs\$name.log" `
            -RedirectStandardError "$ProjectDir\logs\${name}_err.log"
    }
}

Set-Location $ProjectDir

# Kill any duplicate processes (keep only lock-file owner alive)
function Kill-Duplicates($pattern, $lockFile) {
    $lockPath = Join-Path $ProjectDir $lockFile
    $ownerPid = $null
    if (Test-Path $lockPath) {
        $ownerPid = [int](Get-Content $lockPath -ErrorAction SilentlyContinue)
    }
    $procs = @(Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*$pattern*" })
    if ($procs.Count -gt 1) {
        foreach ($p in $procs) {
            if ($p.ProcessId -ne $ownerPid) {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Host "Killed duplicate $pattern PID $($p.ProcessId)"
            }
        }
    }
}

Kill-Duplicates "poster_daemon" "data\poster.lock"
Kill-Duplicates "poller.py"    "data\poller.lock"

# Clear stale locks if owner process is dead
foreach ($lock in @("data\poller.lock", "data\poster.lock")) {
    $lockPath = Join-Path $ProjectDir $lock
    if (Test-Path $lockPath) {
        $pid_str = Get-Content $lockPath -ErrorAction SilentlyContinue
        if ($pid_str) {
            $proc = Get-Process -Id ([int]$pid_str) -ErrorAction SilentlyContinue
            if (-not $proc) {
                Remove-Item $lockPath -Force
                Write-Host "Cleared stale lock: $lock"
            }
        }
    }
}

# Scanner — check via lock file PID
if (-not (Is-AliveViaPid "data\poller.lock")) {
    Remove-Item "$ProjectDir\data\poller.lock" -Force -ErrorAction SilentlyContinue
    Start-Component "scanner" "scanner/poller.py"
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Scanner OK"
}

Start-Sleep -Seconds 2

# Poster — check via lock file PID
if (-not (Is-AliveViaPid "data\poster.lock")) {
    Remove-Item "$ProjectDir\data\poster.lock" -Force -ErrorAction SilentlyContinue
    Start-Component "poster" "poster_daemon.py"
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Poster OK"
}

Start-Sleep -Seconds 2

# Telegram bot — no lock file, use process check
$tgRunning = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*telegram_bot*" }
if (-not $tgRunning) {
    Start-Component "telegram_bot" "-m notifier.telegram_bot"
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Telegram bot OK"
}

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Watchdog check complete."
