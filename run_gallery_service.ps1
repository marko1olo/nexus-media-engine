# ==============================================================================
# Immersion Nexus Gallery & AI Russian Captioner Service Watchdog
# Ensures the gallery server and neural auto-captioner run 24/7.
# Auto-starts on Windows login and survives crashes / reboots.
# ==============================================================================

$GalleryDir = "C:\Users\Admin\Pictures\gALLERY"
$PythonExe = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
$LogFile = "$GalleryDir\service.log"

Set-Location $GalleryDir

function Write-ServiceLog($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $msg"
    Write-Output $line
    try {
        Add-Content -Path $LogFile -Value $line -Encoding utf8
    } catch {}
}

Write-ServiceLog "Gallery service supervisor started."

# Idempotency check: is port 5000 already running and healthy?
function Test-GalleryRunning {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/captioner/status" -TimeoutSec 3 -ErrorAction Stop
        if ($response -and $response.is_running -ne $null) {
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

if (Test-GalleryRunning) {
    Write-ServiceLog "Gallery server is already running and healthy on http://127.0.0.1:5000. Exiting supervisor duplicate."
    exit 0
}

# Supervisor watchdog loop
while ($true) {
    if (Test-GalleryRunning) {
        Start-Sleep -Seconds 10
        continue
    }

    Write-ServiceLog "Starting Python app.py with Florence-2 + MarianMT background captioner..."
    
    try {
        $process = Start-Process -FilePath $PythonExe -ArgumentList "app.py" -WorkingDirectory $GalleryDir -PassThru -NoNewWindow -RedirectStandardOutput "$GalleryDir\app_stdout.log" -RedirectStandardError "$GalleryDir\app_stderr.log"
        Write-ServiceLog "app.py process launched with PID $($process.Id)."
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        Write-ServiceLog "app.py exited with code $exitCode. Restarting in 3 seconds..."
    } catch {
        Write-ServiceLog "Exception running app.py: $_. Retrying in 5 seconds..."
        Start-Sleep -Seconds 2
    }

    Start-Sleep -Seconds 3
}
