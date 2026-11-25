$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    python -m pip install --upgrade --pre -r requirements.txt --target vendor
    if ($LASTEXITCODE -ne 0) { throw "Dependency update failed." }
    Write-Host "Dependencies updated. Restart Video Fetcher to load the new version."
    Write-Host "YouTube also needs Deno >= 2.3 or Node.js >= 22 on PATH or in tools/deno or tools/node."
    Write-Host "Packaged EXEs must be rebuilt to include the updated dependencies."
} finally {
    Pop-Location
}
