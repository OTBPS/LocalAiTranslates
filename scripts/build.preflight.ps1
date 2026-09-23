# Refuse to build over a payload that is still running.
#
# `--clean` deletes the whole payload directory before rebuilding, so a
# packaged application launched from `dist\` holds its own files open and
# the build dies on a PermissionError from inside shutil, twenty frames
# deep, ending in a localised Windows message. Nothing in that names the
# cause.
#
# Only a process running *from the payload directory* matters. An
# installed copy in the tray does not lock anything the build touches --
# including the test installation under this repository, which is why the
# match is against `dist\<payload>` and not the project root.
#
# Shared by the full, client and incremental scripts so the three cannot
# disagree about what counts as blocking.

function Get-PayloadProcesses {
    param([Parameter(Mandatory)] [string[]] $PayloadDirectories)

    $roots = @()
    foreach ($directory in $PayloadDirectories) {
        $roots += [System.IO.Path]::GetFullPath($directory).TrimEnd('\') + '\'
    }

    Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $path = $null
        # Path throws for protected processes we have no business reading.
        try { $path = $_.Path } catch { $path = $null }
        if ([string]::IsNullOrEmpty($path)) {
            $false
        } else {
            $hit = $false
            foreach ($root in $roots) {
                if ($path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $hit = $true
                }
            }
            $hit
        }
    }
}

function Assert-PayloadNotRunning {
    param([Parameter(Mandatory)] [string[]] $PayloadDirectories)

    $holders = @(Get-PayloadProcesses -PayloadDirectories $PayloadDirectories)
    if ($holders.Count -eq 0) { return }

    # English, and ASCII, like every other throw in these scripts.
    # Windows PowerShell reads a .ps1 as ANSI unless it has a BOM, so a
    # non-ASCII literal here breaks the parse rather than the message.
    $lines = $holders | ForEach-Object { "  $($_.ProcessName) (PID $($_.Id)) - $($_.Path)" }
    throw (
        "The build payload is still running, so --clean cannot remove it:`n" +
        ($lines -join "`n") +
        "`nExit the application from its tray icon, or: Stop-Process -Id <PID> -Force"
    )
}
