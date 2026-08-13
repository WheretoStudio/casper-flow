# Build Casper Flow into its distributable artefacts.
#
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#
# Produces three things in <OutDir>\out:
#
#   CasperFlowSetup.exe        the installer, and the download the website links
#   CasperFlow-portable.zip    the same payload, for machines that cannot run one
#   SHA256SUMS.txt             so an unsigned binary can be verified
#
# Pass -SkipInstaller to stop after PyInstaller, which is the fast loop when
# debugging the bundle itself.
#
# Output goes OUTSIDE the repository by default. This tree lives in OneDrive,
# which tries to sync half a gigabyte of build output and holds file handles
# while doing it - the first build failed with "the process cannot access the
# file because it is being used by another process" for exactly that reason.
#
# Bundled models are copied in here rather than listed in casper.spec, because
# two of them come from the HuggingFace cache and their snapshot paths contain a
# revision hash that changes.

param(
    [string]$OutDir = (Join-Path $env:LOCALAPPDATA "CasperFlowBuild"),
    # Empty means "read it from version.py", which is the single source of truth.
    # Hand-maintaining it here as well as in version.py and installer.iss was
    # three chances for one release to disagree with itself about its own number.
    [string]$Version = "",
    [switch]$SkipModels,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }

$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$pyi = Join-Path $PSScriptRoot "venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyi)) {
    throw "pyinstaller missing. Run: .\venv\Scripts\python.exe -m pip install -r requirements-dev.txt"
}

if (-not $Version) {
    $Version = (& $py -c "import version; print(version.__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Version) { throw "Could not read version.py" }
}

$work = Join-Path $OutDir "work"
$dist = Join-Path $OutDir "dist"
$app  = Join-Path $dist "CasperFlow"
$out  = Join-Path $OutDir "out"

Step "Output directory"
Ok $OutDir
if (Test-Path $app) {
    Get-Process CasperFlow -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    # Retried, because this fails for a reason that has nothing to do with the
    # build: Defender scans model.bin as soon as it is written, and holds it open
    # for a few seconds. A real-time scanner winning a race is not a build error.
    $removed = $false
    foreach ($attempt in 1..6) {
        try {
            Remove-Item -Recurse -Force $app -ErrorAction Stop
            $removed = $true
            break
        } catch {
            if ($attempt -eq 1) { Warn "previous build is locked; waiting for it to be released" }
            Start-Sleep -Seconds 2
        }
    }
    if (-not $removed) {
        throw ("Could not delete $app - something still has a file open in it. " +
               "Close Casper Flow and any Explorer window showing that folder.")
    }
}

Step "Regenerating the icon"
# $ErrorActionPreference = "Stop" does not catch a native exit code, so this has
# to be checked by hand. Without it a failed icon build printed "ok" and the
# installer shipped whatever .ico happened to be on disk.
& $py make_icon.py
if ($LASTEXITCODE -ne 0) { throw "make_icon.py failed with exit code $LASTEXITCODE" }
Ok "assets/casper.ico"

if (-not $SkipModels) {
    Step "Verifying the speech models"
    # Before the freeze, because casper.spec reads models/ as it builds.
    #
    # Checked against models/MODELS.lock.json, file by file, so a build cannot
    # quietly ship weights other than the ones the published accuracy figures were
    # measured on. fetch_models.py assembles them; this only ever checks.
    #
    # This replaces a step that copied base.en out of the developer's HuggingFace
    # cache. That made the payload depend on the state of one home directory, and
    # when the cache was empty it warned and carried on - producing an installer
    # with no English model that still told the user "both models are included".
    & $py fetch_models.py --verify
    if ($LASTEXITCODE -ne 0) {
        throw ("The models in models/ are missing or do not match " +
               "models/MODELS.lock.json.`n" +
               "Run:  .\venv\Scripts\python.exe fetch_models.py")
    }
} else {
    Warn "-SkipModels: the payload will have no speech models and is not shippable"
}

Step "Freezing with PyInstaller (--onedir)"
& $pyi casper.spec --noconfirm --clean --distpath $dist --workpath $work
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Ok "built"

Step "Verifying the payload"
# Checked here rather than trusted, because every one of these is something that
# produces a working-looking build that is broken for the user and not for us.
$required = @(
    "CasperFlow.exe",
    "_internal\settings.json",
    "_internal\LICENSE",
    "_internal\THIRD-PARTY-NOTICES.md",
    "_internal\assets\casper.ico",
    "_internal\models\swift-ct2\model.bin",
    "_internal\models\swift-ct2\tokenizer.json",
    "_internal\models\base.en\model.bin",
    "_internal\models\base.en\tokenizer.json"
)
if ($SkipModels) {
    $required = $required | Where-Object { $_ -notlike "*\models\*" }
}
$missing = $required | Where-Object { -not (Test-Path (Join-Path $app $_)) }
if ($missing) {
    throw "The payload is incomplete. Missing:`n  " + ($missing -join "`n  ")
}
Ok "$($required.Count) required files present"

# The frozen app must at least start, import its modules and exit cleanly. A
# packaging mistake otherwise survives every check that only looks at files, and
# surfaces the first time a user opens Settings. `--version` takes no mutex and
# opens no window. It is the exit code that matters here: a windowed build has no
# console, so it prints nowhere.
#
# Start-Process -Wait -PassThru, not `& exe` with $LASTEXITCODE. casper.spec sets
# console=False, and PowerShell does not wait for a windowed-subsystem process -
# the call returns immediately and leaves $LASTEXITCODE untouched. So this check
# used to report whatever the previous native command had exited with, which was
# 0, and passed for every build including a broken one. Probed with
# `--set-profile`, which calls sys.exit(2): $LASTEXITCODE still read 0.
#
# Output goes to temp files and is only shown on failure, since a windowed build
# writes to no console and the exit code alone is not enough to debug from.
$probeOut = Join-Path $env:TEMP "casper-probe-out.txt"
$probeErr = Join-Path $env:TEMP "casper-probe-err.txt"
$probe = Start-Process -FilePath (Join-Path $app "CasperFlow.exe") `
    -ArgumentList "--version" -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput $probeOut -RedirectStandardError $probeErr
if ($probe.ExitCode -ne 0) {
    $detail = @()
    foreach ($f in @($probeOut, $probeErr, (Join-Path $app "casper.log"))) {
        if (Test-Path $f) { $detail += "--- $f ---"; $detail += (Get-Content $f) }
    }
    throw ("The frozen app failed to start: exit $($probe.ExitCode)`n" +
           ($detail -join "`n"))
}
Ok "frozen app starts and exits cleanly"

Step "Payload"
$stats = Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum
Write-Host ("    installed: {0:N1} MB across {1:N0} files" -f ($stats.Sum / 1MB), $stats.Count)
Write-Host "    $app"

if ($SkipInstaller) {
    Write-Host "`n    -SkipInstaller given; stopping before iscc." -ForegroundColor Yellow
    return
}

# ---------------------------------------------------------------- distributables

# Emptied, not just created. Leftovers from a previous or interrupted run sat
# beside the new ones with no way to tell them apart, and SHA256SUMS.txt would
# then describe files that were never built together.
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path $out | Out-Null

Step "Compiling the installer (Inno Setup)"
# winget installs Inno Setup per-user, so %LOCALAPPDATA% comes first. The Program
# Files paths cover a machine-wide install done by hand or by a CI runner.
$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "ISCC.exe not found. Install it with: winget install --id JRSoftware.InnoSetup"
}
Ok (Split-Path $iscc -Parent)

& $iscc "/DPayloadDir=$app" "/DOutputDir=$out" "/DAppVersion=$Version" `
    (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$setup = Join-Path $out "CasperFlowSetup.exe"
if (-not (Test-Path $setup)) { throw "iscc reported success but $setup is missing" }
Ok ("CasperFlowSetup.exe  {0:N1} MB" -f ((Get-Item $setup).Length / 1MB))

Step "Building the portable zip"
# The same payload, for machines where an installer cannot run. Zipping $dist
# rather than $app so the archive contains a CasperFlow\ folder instead of
# scattering 1,500 files into whatever directory the user extracted it in.
#
# The note goes in $dist, beside the folder rather than inside it, so it appears
# at the root of the zip without also being installed by the installer.
$note = Join-Path $dist "HOW-TO-RUN.txt"
@"
Casper Flow $Version - portable

1. Move the CasperFlow folder anywhere you like. Keep it together; the .exe
   needs the files beside it.
2. Run CasperFlow\CasperFlow.exe
3. Look for the microphone icon in the system tray, near the clock. You may
   need to click the ^ arrow to see it.

Hold your push-to-talk key for two seconds and talk. The text appears at your
cursor. Settings and the log are written next to CasperFlow.exe.

This portable copy has no Start Menu entry, no launch-at-login option and no
uninstaller - to remove it, delete the folder. If you can run an installer,
CasperFlowSetup.exe is the better option.

Everything runs on your machine. No account, no network, no upload.
"@ | Set-Content -Path $note -Encoding UTF8

$zip = Join-Path $out "CasperFlow-portable.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }

# CreateFromDirectory takes everything in $dist, and only $app is cleaned at the
# start of a run - so a folder left by an earlier or renamed build would ship
# inside the portable zip. Remove anything that is not part of this build.
foreach ($stray in Get-ChildItem $dist) {
    if ($stray.Name -ne "CasperFlow" -and $stray.Name -ne "HOW-TO-RUN.txt") {
        Warn "removing stray payload item: $($stray.Name)"
        Remove-Item -Recurse -Force $stray.FullName
    }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
# .NET rather than Compress-Archive: Compress-Archive takes minutes on a payload
# this size and this does not.
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $dist, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
Ok ("CasperFlow-portable.zip  {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))

Step "Checksums"
# Published so a cautious user can verify an unsigned binary rather than trust it.
$sums = Join-Path $out "SHA256SUMS.txt"
$lines = foreach ($f in @($setup, $zip)) {
    $h = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
    "{0}  {1}" -f $h, (Split-Path $f -Leaf)
}
$lines | Set-Content -Path $sums -Encoding ASCII
$lines | ForEach-Object { Write-Host "    $_" }

Step "Result"
Write-Host "    $out"
foreach ($f in (Get-ChildItem $out -File | Sort-Object Name)) {
    Write-Host ("    {0,-28} {1,9:N1} MB" -f $f.Name, ($f.Length / 1MB))
}

# Computed into variables and interpolated. The obvious spelling of this,
# `Write-Host @"...{0}..."@ -f $x`, binds -f to Write-Host rather than to the
# string, and fails with an unrelated complaint about ForegroundColor.
$setupMB = "{0:N0} MB" -f ((Get-Item $setup).Length / 1MB)
$setupSha = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()

Write-Host @"

Next:
  Install it:    $setup
  Or run it in place:
                 $app\CasperFlow.exe

Website constants for Phase 5 (website/src/components/site/constants.ts):
  version        $Version
  installerSize  $setupMB
  sha256         $setupSha
"@
