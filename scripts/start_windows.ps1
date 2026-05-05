param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Build -or -not (docker image inspect finally:latest 2>$null)) {
    docker build -t finally:latest .
}

if (docker ps -a --format "{{.Names}}" | Select-String -Quiet "^finally$") {
    docker stop finally 2>$null | Out-Null
    docker rm finally 2>$null | Out-Null
}

docker run `
    --detach `
    --name finally `
    --volume finally-data:/app/db `
    --publish 8000:8000 `
    --env-file .env `
    finally:latest | Out-Null

Write-Host "FinAlly is running at http://localhost:8000"
