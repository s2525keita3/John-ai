# Create GitHub repo and push (requires: GitHub CLI "gh")
# Run from project root:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\push-to-github.ps1
# Custom repo name:
#   .\scripts\push-to-github.ps1 -RepoName "my-app-name"

param(
    [string]$RepoName = "homon-kensu-app"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    $env:Path += ";$env:ProgramFiles\GitHub CLI"
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) not found. Run: winget install --id GitHub.cli -e"
}

# gh auth status writes to stderr when not logged in; cmd hides it so -Stop does not abort
cmd /c "gh auth status >nul 2>nul"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[Login] First time only: sign in to GitHub (browser will open)." -ForegroundColor Cyan
    Write-Host ""
    gh auth login -h github.com -p https -w
}

Write-Host ""
Write-Host "[Push] Creating repo '$RepoName' and pushing..." -ForegroundColor Cyan
gh repo create $RepoName --private --source=. --remote=origin --push

Write-Host ""
Write-Host "Done. Open the repo on GitHub to copy the URL." -ForegroundColor Green
