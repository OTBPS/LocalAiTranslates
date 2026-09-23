param(
    [string]$Python = "$PSScriptRoot\..\.venv\Scripts\python.exe",
    [string]$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    # No default on purpose. This value is the promise that the patch may
    # be applied to a given installation, and the patch carries only the
    # executable and the assets directory -- the Python runtime, PySide6,
    # PaddleOCR and llama.cpp all stay as the base install left them. The
    # old default of 0.3.0 was correct when this script was written and
    # then rotted, because every release since has passed the value
    # explicitly. A bare invocation silently widened the promise by five
    # releases, which is the exact failure the value exists to prevent.
    [string]$MinimumBaseVersion = "",
    [string]$SignToolName = "",
    [switch]$SkipAppBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$updateDir = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'dist\updates'))
$pytestTemp = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build\pytest-$PID"))
if (-not $updateDir.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unexpected update output directory'
}
if (-not $pytestTemp.StartsWith((Join-Path $projectRoot 'build') + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unexpected test temporary directory'
}

. (Join-Path $PSScriptRoot 'build.preflight.ps1')
# Before anything slow: --clean wipes the payload directory, and a
# packaged application still running from it holds its own files
# open. Failing here names the cause; failing later does not.
Assert-PayloadNotRunning -PayloadDirectories @((Join-Path $projectRoot 'dist\ScreenTranslator'))

Push-Location $projectRoot
try {
    & $Python -m ruff check screen_translator tests scripts
    if ($LASTEXITCODE) { throw 'Static checks failed' }
    & $Python -m pytest -q -p no:cacheprovider --basetemp $pytestTemp --cov=screen_translator --cov-fail-under=55 --cov-report=term
    if ($LASTEXITCODE) { throw 'Tests failed' }

    $AppVersion = (& $Python -c "from screen_translator.version import __version__; print(__version__)").Trim()
    if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') { throw "Application version must be numeric SemVer: $AppVersion" }
    if (-not $MinimumBaseVersion) { throw 'Minimum base version is required: pass -MinimumBaseVersion <previous release>, for example 0.7.0' }
    if ($MinimumBaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw "Minimum base version must be numeric SemVer: $MinimumBaseVersion" }
    $AppFileVersion = "$AppVersion.0"

    if (-not $SkipAppBuild) {
        # --clean is not optional for a release build. PyInstaller's
        # staleness check for the EXE stage compares paths, not
        # contents, so a regenerated icon at the same path is reused
        # from the work directory: the payload updates and the icon
        # embedded in the exe does not. Found exactly that way.
        & $Python -m PyInstaller --noconfirm --clean ScreenTranslator.spec
        if ($LASTEXITCODE) { throw 'PyInstaller failed' }
    }

    $launcher = 'dist\ScreenTranslator\ScreenTranslator.exe'
    $asset = 'dist\ScreenTranslator\_internal\screen_translator\assets\check.svg'
    if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $asset)) {
        throw 'Incremental payload is incomplete; build the app first'
    }

    New-Item -ItemType Directory -Path $updateDir -Force | Out-Null
    Get-ChildItem -LiteralPath $updateDir -Filter 'ScreenTranslator-*-Update.exe' -File | Remove-Item -Force
    Get-ChildItem -LiteralPath $updateDir -Filter 'ScreenTranslator-*-Update.manifest.json' -File | Remove-Item -Force

    if (-not (Test-Path -LiteralPath $Iscc)) { $Iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" }
    if (-not (Test-Path -LiteralPath $Iscc)) { throw 'Inno Setup compiler not found; pass -Iscc path' }
    $compilerArguments = @(
        "/DAppVersion=$AppVersion",
        "/DAppFileVersion=$AppFileVersion",
        "/DMinimumBaseVersion=$MinimumBaseVersion",
        '/Q',
        'installer.update.iss'
    )
    if ($SignToolName) { $compilerArguments = @("/DSignToolName=$SignToolName") + $compilerArguments }
    & $Iscc @compilerArguments
    if ($LASTEXITCODE) { throw 'Incremental installer compilation failed' }

    $package = Join-Path $updateDir "ScreenTranslator-$AppVersion-Update.exe"
    $manifest = Join-Path $updateDir "ScreenTranslator-$AppVersion-Update.manifest.json"
    & $Python scripts\release_manifest.py $package $manifest $AppVersion incremental --minimum-base-version $MinimumBaseVersion --verify
    if ($LASTEXITCODE) { throw 'Release manifest verification failed' }

    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $package
    [pscustomobject]@{
        Package = $package
        Manifest = $manifest
        MinimumBaseVersion = $MinimumBaseVersion
        SizeMB = [math]::Round((Get-Item -LiteralPath $package).Length / 1MB, 2)
        SHA256 = $hash.Hash
        Signed = [bool]$SignToolName
    } | Format-List
} finally {
    if (Test-Path -LiteralPath $pytestTemp) {
        Remove-Item -LiteralPath $pytestTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
