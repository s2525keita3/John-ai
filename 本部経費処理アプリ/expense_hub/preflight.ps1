# push 前の自動チェック（学習ログ #4 の再発防止）。通らなければ push しない。
#   powershell -NoProfile -ExecutionPolicy Bypass -File 本部経費処理アプリ\expense_hub\preflight.ps1 [-AmexCsv "...activity (28).csv"]
# 1) 全テスト  2) 通年バックテストの自動確認率が前回（baseline.json）より下がっていないか
param([string]$AmexCsv = "$env:USERPROFILE\Downloads\activity (28).csv")
$ErrorActionPreference = "Stop"
$app = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location (Join-Path $app "本部経費処理アプリ")
$env:PYTHONIOENCODING = "utf-8"

Write-Host "== 1/2 テスト"
py -3 -m pytest tests expense_hub/tests -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { Write-Host "[NG] テスト失敗。push しない"; exit 1 }

if (-not (Test-Path $AmexCsv)) { Write-Host "[SKIP] 通年CSVが無いのでバックテスト省略: $AmexCsv"; exit 0 }
Write-Host "== 2/2 通年バックテスト"
$out = Join-Path $env:TEMP "expense_hub_backtest.json"
py -3 -m expense_hub.backtest $AmexCsv --months 1-8 --json $out | Select-Object -Last 1
$res = Get-Content $out -Encoding UTF8 | ConvertFrom-Json
$auto = ($res | Measure-Object -Property 自動確認 -Sum).Sum
$rv   = ($res | Measure-Object -Property 要確認 -Sum).Sum
$rate = [math]::Round($auto / ($auto + $rv) * 100, 1)
$base = Join-Path $PSScriptRoot "backtest_baseline.json"
if (Test-Path $base) {
  $b = Get-Content $base -Encoding UTF8 | ConvertFrom-Json
  if ($rate -lt $b.rate) { Write-Host "[NG] 自動確認率が下がった: $($b.rate)% → $rate%。push しない"; exit 1 }
  Write-Host "[OK] 自動確認率 $rate% （前回 $($b.rate)%）"
} else { Write-Host "[OK] 自動確認率 $rate% （初回・基準を保存）" }
@{ rate = $rate; auto = $auto; review = $rv; at = (Get-Date -Format s) } | ConvertTo-Json | Set-Content $base -Encoding UTF8
Write-Host "[OK] preflight 通過"
