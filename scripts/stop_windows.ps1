$ErrorActionPreference = "Stop"

if (docker ps -a --format "{{.Names}}" | Select-String -Quiet "^finally$") {
    docker stop finally 2>$null | Out-Null
    docker rm finally 2>$null | Out-Null
    Write-Host "Stopped FinAlly."
} else {
    Write-Host "FinAlly is not running."
}
