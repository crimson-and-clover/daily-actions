<#
.SYNOPSIS
一键初始化并推送各智能体纯净的状态孤儿分支 (state/*)
#>
param(
    [string[]]$Modules = @("market-fx", "paper-agent", "world-news", "reviewer-radar")
)

$ErrorActionPreference = "Stop"
$currentBranch = git branch --show-current

foreach ($mod in $Modules) {
    $stateBranch = "state/$mod"
    $tempBranch = "orphan-init-$mod-$PID"

    Write-Host "==> 正在初始化孤儿分支: $stateBranch..."
    git checkout --orphan $tempBranch 2>$null | Out-Null
    git rm -rf . 2>$null | Out-Null

    New-Item -ItemType Directory -Force -Path $mod | Out-Null
    $initJson = @"
{
  "version": 1,
  "initialized_at": "$((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
}
"@
    Set-Content -Path "$mod/history.json" -Value $initJson -Encoding utf8

    git add -f "$mod/history.json"
    git commit -m "chore($mod): initialize clean orphan state branch" 2>$null | Out-Null
    git push -f origin "${tempBranch}:${stateBranch}"

    git checkout $currentBranch 2>$null | Out-Null
    git branch -D $tempBranch 2>$null | Out-Null
    Write-Host "==> $stateBranch 初始化并推送成功。"
}

Write-Host "==> 所有指定的状态分支已全部初始化完毕！"
