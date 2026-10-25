# Spaceplane Takeoff Assistant - bootstrap installer for Windows (PowerShell 5.1+ or 7+).
#
#   irm https://raw.githubusercontent.com/OWNER/REPO/main/install.ps1 | iex
#
# Fetches the repo into %LOCALAPPDATA%\TakeoffAssistant\repo, then launches the interactive manager.
# Optional env vars: TAKEOFF_ASSISTANT_REPO, TAKEOFF_ASSISTANT_REF, TAKEOFF_ASSISTANT_YES=1
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = if ($env:TAKEOFF_ASSISTANT_REPO) { $env:TAKEOFF_ASSISTANT_REPO } else { 'OWNER/REPO' }
$Ref = if ($env:TAKEOFF_ASSISTANT_REF) { $env:TAKEOFF_ASSISTANT_REF } else { 'main' }
$AppHome = if ($env:TAKEOFF_ASSISTANT_HOME) { $env:TAKEOFF_ASSISTANT_HOME } else { Join-Path $env:LOCALAPPDATA 'TakeoffAssistant' }
$GitUrl = if ($env:TAKEOFF_ASSISTANT_GIT_URL) { $env:TAKEOFF_ASSISTANT_GIT_URL } else { "https://github.com/$Repo.git" }
$Src = Join-Path $AppHome 'repo'

function Say($m) { Write-Host "==> $m" }
function Fail($m) { Write-Host "!!  $m" -ForegroundColor Red; throw $m }

if ($Repo -eq ('OWNER' + '/REPO') -and -not $env:TAKEOFF_ASSISTANT_GIT_URL) {
    Fail 'This script still has the OWNER/REPO placeholder. Run tools/set_repo.py YOUR_USER/YOUR_REPO first.'
}

# ---- Python 3.8+ (py launcher, python, python3) ---------------------------------
function Find-Python {
    $candidates = @(@('py', '-3'), @('python'), @('python3'))
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $extra = @()
        if ($c.Length -gt 1) { $extra = $c[1..($c.Length - 1)] }
        try {
            & $exe @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                # Resolve the real interpreter path. The Microsoft Store stub fails the check above.
                $real = & $exe @extra -c "import sys; print(sys.executable)"
                if ($real) { return $real.Trim() }
            }
        }
        catch { }
    }
    return $null
}

$Py = Find-Python
if (-not $Py) {
    Write-Host '!!  Python 3.8 or newer is required.' -ForegroundColor Red
    Write-Host '    Install it with:  winget install Python.Python.3.12'
    Write-Host '    then open a NEW terminal and re-run this command.'
    throw 'Python not found'
}

# ---- Fetch source ----------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $AppHome | Out-Null
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $Src '.git')) {
        Say 'Updating existing checkout'
        git -C $Src fetch --quiet origin $Ref
        if ($LASTEXITCODE -ne 0) { Fail 'git fetch failed' }
        git -C $Src reset --hard --quiet FETCH_HEAD
    }
    else {
        Say "Cloning $GitUrl"
        if (Test-Path $Src) { Remove-Item -Recurse -Force $Src }
        git clone --quiet --branch $Ref $GitUrl $Src
    }
    if ($LASTEXITCODE -ne 0) { Fail 'git failed' }
}
else {
    Say "Downloading $Repo@$Ref (git not found)"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('takeoff-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'src.zip'
    Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Ref" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'x') -Force
    $top = Get-ChildItem (Join-Path $tmp 'x') | Select-Object -First 1
    if (Test-Path $Src) { Remove-Item -Recurse -Force $Src }
    Move-Item $top.FullName $Src
    Remove-Item -Recurse -Force $tmp
}

$Manager = Join-Path $Src 'installer\manager.py'
if (-not (Test-Path $Manager)) { Fail "Download looks wrong: $Manager not found." }

# ---- Hand over to the manager -----------------------------------------------------
$mArgs = @($Manager, 'install', '--repo', $Repo, '--ref', $Ref)
if ($env:TAKEOFF_ASSISTANT_YES -eq '1') { $mArgs += '--yes' }
# Note: no 'exit' here - under 'irm | iex' that would close the user's terminal window.
& $Py @mArgs
