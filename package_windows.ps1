$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $pythonPath = Join-Path $PSScriptRoot '.runtime\package-venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw 'Create the packaging venv described in README.md first.'
    }
    # Build in a staging directory; never let PyInstaller replace user data folders.
    & $pythonPath -m PyInstaller --noconfirm --distpath .runtime\package-output --workpath .runtime\isolated-build VideoFetcher.spec
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
    $stagingDirectory = Join-Path $PSScriptRoot '.runtime\package-output\VideoFetcher'
    $outputDirectory = Join-Path $PSScriptRoot 'dist\updated\VideoFetcher'
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $stagingDirectory 'VideoFetcher.exe') -Destination $outputDirectory -Force
    Copy-Item -LiteralPath (Join-Path $stagingDirectory '_internal') -Destination $outputDirectory -Recurse -Force
    Write-Host "Updated application: $outputDirectory\VideoFetcher.exe"
} finally {
    Pop-Location
}
