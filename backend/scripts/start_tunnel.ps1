# Starts a Cloudflare quick tunnel to the backend (http://localhost:8000) and writes its address into
# backend/.env (PUBLIC_BASE_URL: HOD/admin email links, project file links) and the app's .env
# (EXPO_PUBLIC_API_BASE_URL). Then restart the backend, and Expo with -c.
#
#   powershell -ExecutionPolicy Bypass -File backend\scripts\start_tunnel.ps1
#
# Quick tunnels get a new address each time and stop working for good if the connection drops for long
# (e.g. the laptop sleeps): just run this again.

$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$metrics = "127.0.0.1:20241"
$backend = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $backend

if (-not (Test-Path $cloudflared)) { Write-Error "cloudflared not found at $cloudflared"; exit 1 }

$proc = Start-Process -FilePath $cloudflared -NoNewWindow -PassThru -ArgumentList @(
    "tunnel", "--protocol", "http2", "--url", "http://localhost:8000", "--metrics", $metrics
)

# cloudflared reports the tunnel's hostname on its metrics server once it's created.
$hostname = $null
for ($i = 0; $i -lt 60 -and -not $hostname; $i++) {
    Start-Sleep -Seconds 1
    try { $hostname = (Invoke-RestMethod -Uri "http://$metrics/quicktunnel" -TimeoutSec 2).hostname } catch { }
    if ($proc.HasExited) { Write-Error "cloudflared stopped."; exit 1 }
}
if (-not $hostname) { Write-Error "No tunnel address after 60 s."; Stop-Process -Id $proc.Id; exit 1 }
$url = "https://$hostname"

function Set-EnvValue([string]$file, [string]$name, [string]$value) {
    $lines = [System.IO.File]::ReadAllLines($file)
    $found = $false
    for ($j = 0; $j -lt $lines.Length; $j++) {
        if ($lines[$j] -match "^$name=") { $lines[$j] = "$name=$value"; $found = $true }
    }
    if (-not $found) { $lines += "$name=$value" }
    # UTF-8 without a BOM: a BOM would break the first line of a .env file.
    [System.IO.File]::WriteAllLines($file, $lines, (New-Object System.Text.UTF8Encoding $false))
}

Set-EnvValue (Join-Path $backend ".env") "PUBLIC_BASE_URL" $url
Set-EnvValue (Join-Path $root ".env") "EXPO_PUBLIC_API_BASE_URL" $url

Write-Host ""
Write-Host "Tunnel: $url" -ForegroundColor Green
Write-Host "Updated backend\.env (PUBLIC_BASE_URL) and .env (EXPO_PUBLIC_API_BASE_URL)." -ForegroundColor Green
Write-Host "Salesforce webhooks (send the new addresses to the Salesforce team):" -ForegroundColor Green
Write-Host "  Lead status:    $url/webhooks/salesforce/lead-updated" -ForegroundColor Green
Write-Host "  Partner status: $url/webhooks/salesforce/partner-updated" -ForegroundColor Green
Write-Host "Now restart Expo with: npx expo start --tunnel ngrok -c" -ForegroundColor Yellow
Write-Host "The backend picks up the new address by itself only if it was started with --reload-include .env:" -ForegroundColor Yellow
Write-Host "  .venv\Scripts\uvicorn app.main:app --reload --reload-include .env --host 0.0.0.0 --port 8000" -ForegroundColor Yellow
Write-Host "Otherwise restart it (Ctrl+C, then start it again)." -ForegroundColor Yellow
Write-Host "Keep this window open. Ctrl+C stops the tunnel." -ForegroundColor Yellow
Write-Host ""

Wait-Process -Id $proc.Id
