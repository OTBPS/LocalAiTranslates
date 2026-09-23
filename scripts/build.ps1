param(
    [string]$Python = "$PSScriptRoot\..\.venv\Scripts\python.exe",
    [string]$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [string]$SignToolName = "",
    [switch]$SkipAppBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$installerDir = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'dist\installer'))
$pytestTemp = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build\pytest-$PID"))
if (-not $installerDir.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unexpected installer output directory'
}
if (-not $pytestTemp.StartsWith((Join-Path $projectRoot 'build') + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unexpected test temporary directory'
}

Push-Location $projectRoot
try {
    & $Python -m ruff check screen_translator tests scripts
    if ($LASTEXITCODE) { throw 'Static checks failed' }
    & $Python -m pytest -q -p no:cacheprovider --basetemp $pytestTemp --cov=screen_translator --cov-fail-under=55 --cov-report=term
    if ($LASTEXITCODE) { throw 'Tests failed' }
    & $Python -c "import paddle; assert paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0, 'Paddle GPU runtime is unavailable'"
    if ($LASTEXITCODE) { throw 'Paddle GPU preflight failed' }
    if (-not (Test-Path -LiteralPath 'runtime\llama\llama-server.exe')) { throw 'Run scripts/prepare_runtime.py first' }

    $AppVersion = (& $Python -c "from screen_translator.version import __version__; print(__version__)").Trim()
    if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') { throw "Application version must be numeric SemVer: $AppVersion" }
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
    if (-not (Test-Path -LiteralPath 'dist\ScreenTranslator\ScreenTranslator.exe')) {
        throw 'Application payload is missing; build the app first'
    }

    if (-not (Test-Path -LiteralPath $Iscc)) { $Iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" }
    if (-not (Test-Path -LiteralPath $Iscc)) { throw 'Inno Setup compiler not found; pass -Iscc path' }

    New-Item -ItemType Directory -Path $installerDir -Force | Out-Null
    Get-ChildItem -LiteralPath $installerDir -Filter 'ScreenTranslator-*-Setup.exe' -File | Remove-Item -Force
    Get-ChildItem -LiteralPath $installerDir -Filter 'ScreenTranslator-*-Setup.manifest.json' -File | Remove-Item -Force

    $compilerArguments = @("/DAppVersion=$AppVersion", "/DAppFileVersion=$AppFileVersion", '/Q', 'installer.iss')
    if ($SignToolName) { $compilerArguments = @("/DSignToolName=$SignToolName") + $compilerArguments }
    & $Iscc @compilerArguments
    if ($LASTEXITCODE) { throw 'Installer compilation failed' }

    $package = Join-Path $installerDir "ScreenTranslator-$AppVersion-Setup.exe"
    $manifest = Join-Path $installerDir "ScreenTranslator-$AppVersion-Setup.manifest.json"
    & $Python scripts\release_manifest.py $package $manifest $AppVersion full --verify
    if ($LASTEXITCODE) { throw 'Release manifest verification failed' }

    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $package
    [pscustomobject]@{
        Package = $package
        Manifest = $manifest
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
