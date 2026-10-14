# PowerShell high-speed launcher and environment manager for A.R.C. Vision on Windows.
# Detects bundled standalone Python runtimes, monitors TCP server readiness, and opens the user interface.
# Handles background process spawning, single-stream log redirection, and GUI error message alerts.

$ErrorActionPreference = "SilentlyContinue"

# 1. Resolve project directories to full absolute paths safely
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = (Get-Location).Path }
if (Test-Path -LiteralPath $ScriptDir) {
    $ScriptDir = (Resolve-Path -LiteralPath $ScriptDir).Path
}
Set-Location -LiteralPath $ScriptDir

$LogFile = Join-Path $ScriptDir "server_output.log"
$InputFolder = Join-Path $ScriptDir "input"
$OutputFolder = Join-Path $ScriptDir "output"
$PythonWinDir = Join-Path $ScriptDir ".python_win"
$LauncherPy = Join-Path $ScriptDir "launcher_win.py"

if (-not (Test-Path -LiteralPath $InputFolder)) { New-Item -ItemType Directory -Force -Path $InputFolder | Out-Null }
if (-not (Test-Path -LiteralPath $OutputFolder)) { New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null }

# High-speed non-blocking TCP port probe (<1ms latency)
function Test-ServerPort {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect("127.0.0.1", 8000, $null, $null)
        $ready = $iar.AsyncWaitHandle.WaitOne(60, $false)
        if ($ready -and $tcp.Connected) {
            $tcp.EndConnect($iar)
            $tcp.Close()
            return $true
        }
        $tcp.Close()
        return $false
    } catch {
        return $false
    }
}

# 2. Instant check: If server is already running, open browser and exit immediately (<0.1s)
if (Test-ServerPort) {
    Start-Process "http://127.0.0.1:8000/loading.html"
    exit 0
}

# 3. Locate Python executable (Fast-Path: bundled standalone runtime)
$pyExe = Join-Path $PythonWinDir "python.exe"
$pywExe = Join-Path $PythonWinDir "pythonw.exe"

# If bundled runtime is not found, check virtualenv or system Python
if (-not (Test-Path -LiteralPath $pyExe)) {
    $venvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPy) {
        $pyExe = (Resolve-Path -LiteralPath $venvPy).Path
        $pywExe = (Resolve-Path -LiteralPath (Join-Path $ScriptDir ".venv\Scripts\pythonw.exe")).Path
    } else {
        $candidates = @("pythonw", "py", "python", "python3")
        foreach ($c in $candidates) {
            $p = Start-Process -FilePath $c -ArgumentList '-c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"' -Wait -WindowStyle Hidden -PassThru -ErrorAction SilentlyContinue
            if ($p -and $p.ExitCode -eq 0) { $pyExe = $c; $pywExe = $c; break }
        }
    }
}

# 4. Primary Launch: Delegate to launcher_win.py with pythonw if present
if ((Test-Path -LiteralPath $LauncherPy) -and ((Test-Path -LiteralPath $pywExe) -or (Test-Path -LiteralPath $pyExe))) {
    $runner = if (Test-Path -LiteralPath $pywExe) { $pywExe } else { $pyExe }
    Start-Process -FilePath $runner -ArgumentList "launcher_win.py" -WorkingDirectory $ScriptDir -WindowStyle Hidden
    exit 0
}

# 5. Direct Fallback Process Launch with single-stream log redirection
if (Test-Path -LiteralPath $LogFile) {
    try { Remove-Item -Force -LiteralPath $LogFile -ErrorAction SilentlyContinue } catch {}
}

$runner = if (Test-Path -LiteralPath $pyExe) { $pyExe } else { $pywExe }
$cmdArgs = "/c `"`"$runner`" server.py > `"$LogFile`" 2>&1`""
$serverProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList $cmdArgs `
    -WorkingDirectory $ScriptDir `
    -WindowStyle Hidden `
    -PassThru

# 6. Fast-polling loop (checks every 100ms; opens browser when server responds)
$opened = $false
for ($i = 0; $i -lt 300; $i++) {
    Start-Sleep -Milliseconds 100
    if (Test-ServerPort) {
        Start-Sleep -Milliseconds 100
        Start-Process "http://127.0.0.1:8000/loading.html"
        $opened = $true
        break
    }
    if ($serverProc -and $serverProc.HasExited) {
        break
    }
}

if (-not $opened) {
    $errSnippet = ""
    if (Test-Path -LiteralPath $LogFile) {
        $errSnippet = Get-Content -LiteralPath $LogFile -Tail 20 -ErrorAction SilentlyContinue | Out-String
    }
    try {
        [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
        $msg = if ($errSnippet.Trim()) { "A.R.C. Vision server could not start.`n`nError details:`n$errSnippet" } else { "A.R.C. Vision server is taking longer than expected to initialize.`nPlease check 'server_output.log' in 'Source Code\Back End' for details." }
        [System.Windows.Forms.MessageBox]::Show($msg, "A.R.C. Vision Startup Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch {}
    exit 1
}
