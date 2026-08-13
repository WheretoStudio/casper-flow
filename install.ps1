# Casper Flow - DEVELOPER setup, from a source checkout.
#
#     powershell -ExecutionPolicy Bypass -File install.ps1
#
# Requires Python 3.10 or newer, and leaves you with a venv and a source tree.
#
# THIS IS NOT HOW USERS INSTALL CASPER FLOW. They download
# CasperFlowSetup.exe, double-click it, and answer a wizard - no Python, no
# PowerShell, no execution policy to bypass. Sending this command to someone who
# is not a programmer would be asking them to run a script they cannot read, from
# a project asking them to trust it with a keyboard hook.
#
# If you want the user-facing artefacts, build them: build_installer.ps1.

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "    $msg" -ForegroundColor Red }

Set-Location -Path $PSScriptRoot

Write-Host "=== Casper Flow - developer setup from source ===" -ForegroundColor Cyan
Write-Host "    Users install CasperFlowSetup.exe instead." -ForegroundColor DarkGray

# ---------------------------------------------------------------- Python
Write-Step "Locating Python 3.10+"

# `python` may be the Windows Store stub, which exists on PATH but does nothing
# useful, so probe candidates and check the reported version rather than
# trusting that the command resolves.
$candidates = @()
foreach ($name in @("python", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
}
# py launcher can point at interpreters that aren't on PATH
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    foreach ($tag in @("-3.12", "-3.11", "-3.10", "-3")) {
        $p = (& py $tag -c "import sys; print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
    }
}

$python = $null
foreach ($c in ($candidates | Select-Object -Unique)) {
    $ver = (& $c -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
    $parts = $ver.Trim().Split('.')
    if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) {
        $python = $c
        Write-Ok "Using Python $($ver.Trim()) at $c"
        break
    } else {
        Write-Warn "Skipping Python $($ver.Trim()) at $c (need 3.10+)"
    }
}

if (-not $python) {
    Write-Err "No suitable Python found. Install Python 3.10+ from https://python.org"
    Write-Err "and tick 'Add Python to PATH' during setup."
    exit 1
}

# ------------------------------------------------------------------ venv
Write-Step "Creating virtual environment (.\venv)"
if (-not (Test-Path "venv\Scripts\python.exe")) {
    & $python -m venv venv
    if ($LASTEXITCODE -ne 0) { Write-Err "venv creation failed"; exit 1 }
    Write-Ok "venv created"
} else {
    Write-Ok "venv already exists - reusing"
}

# Call the venv interpreter directly. No Activate.ps1 needed, so this works
# regardless of the caller's execution policy.
$vpy = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

Write-Step "Upgrading pip"
& $vpy -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Write-Warn "pip upgrade failed - continuing" }

Write-Step "Installing dependencies from requirements.txt"
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Err "Dependency install failed"; exit 1 }
Write-Ok "Core dependencies installed"

# ------------------------------------------------------- optional extras
Write-Step "Optional backends"
$extras = @(
    @{ Name = "groq";      Prompt = "Groq client (fast cloud Whisper + LLM)?"; Default = "n" },
    @{ Name = "anthropic"; Prompt = "Anthropic client (Claude polish)?";       Default = "n" },
    @{ Name = "requests";  Prompt = "requests (needed for Ollama offline polish)?"; Default = "y" }
)
foreach ($e in $extras) {
    $d = $e.Default
    $ans = Read-Host "    Install $($e.Prompt) (y/n) [$d]"
    if ([string]::IsNullOrWhiteSpace($ans)) { $ans = $d }
    if ($ans -eq "y") {
        & $vpy -m pip install $e.Name
        if ($LASTEXITCODE -eq 0) { Write-Ok "$($e.Name) installed" } else { Write-Warn "$($e.Name) failed" }
    }
}

# ------------------------------------------------------------------ .env
Write-Step "API keys"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok "Created .env from template"
    Write-Warn "Edit it to add your keys:  notepad .env"
    Write-Warn "No keys? Fine - local transcription works offline and the"
    Write-Warn "polish step is skipped automatically."
} else {
    Write-Ok ".env already exists - left untouched"
}

# ----------------------------------------------------------- self-check
Write-Step "Running self-check (doctor.py)"
& $vpy doctor.py
$doctor = $LASTEXITCODE

Write-Host "`n=== Install complete ===" -ForegroundColor Green
if ($doctor -ne 0) {
    Write-Warn "doctor.py reported problems above - fix those before first use."
}
Write-Host @"

Start Casper Flow:
  Double-click start_casper.bat
  (or run: .\venv\Scripts\pythonw.exe main.py)

Default hotkey: hold [Caps Lock] for 2 seconds, speak, release.
A shorter press just toggles Caps Lock as usual.
Change the key and the 2s threshold in settings.json.
Tray icon -> Launch at Login to autostart.
"@
