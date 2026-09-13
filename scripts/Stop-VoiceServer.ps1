#Requires -Version 5.1
# ポート 8765 で待ち受けているプロセスを停止します（手動起動・タスク起動のどちらも対象）。
$ErrorActionPreference = "SilentlyContinue"
$Port = 8765

Stop-ScheduledTask -TaskName "VoiceToNotionUvicorn" -ErrorAction SilentlyContinue

$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "ポート $Port で待ち受けているプロセスはありません。"
    exit 0
}

$pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $pids) {
    if ($procId -lt 1) { continue }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) {
        Stop-Process -Id $procId -Force
        Write-Host "停止しました: PID $procId ($($p.ProcessName))"
    }
}
