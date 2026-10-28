<#
.SYNOPSIS
一键安全初始化各智能体状态孤儿分支 (state/*)
.DESCRIPTION
1. 先检查远端是否已存在该分支，若已存在则直接跳过，防止覆盖历史；
2. 全程在系统临时目录中独立操作，绝不干扰当前工作区；
3. 根目录仅放置白名单专属 .gitignore，只允许 track 该模块专属目录，不预置业务数据文件；
4. 严格校验所有原生 git 命令退出码，杜绝静默失败。
#>
param(
    [string[]]$Modules = @("inbox-agent", "market-fx", "paper-agent", "world-news", "reviewer-radar")
)

$ErrorActionPreference = "Stop"

$repoUrl = git remote get-url origin 2>$null
if (-not $repoUrl) {
    Write-Error "未找到远程仓库 origin 地址"
    exit 1
}

$tempBase = Join-Path ([System.IO.Path]::GetTempPath()) ("state-init-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempBase | Out-Null

try {
    foreach ($mod in $Modules) {
        $stateBranch = "state/$mod"

        # 1. 检查远端是否已存在该状态分支
        $remoteHead = git ls-remote --heads $repoUrl $stateBranch
        if ($LASTEXITCODE -ne 0) {
            throw "探测远端 $stateBranch 分支状态失败 (退出码: $LASTEXITCODE)"
        }
        if ($remoteHead -and $remoteHead.Trim()) {
            Write-Host "[跳过] 远端已存在 $stateBranch 分支，保留既有历史状态。"
            continue
        }

        Write-Host "==> [初始化] 远端不存在 $stateBranch，正在安全创建..."

        $workDir = Join-Path $tempBase $mod
        New-Item -ItemType Directory -Force -Path $workDir | Out-Null
        Push-Location $workDir

        try {
            git init -q
            if ($LASTEXITCODE -ne 0) { throw "git init 失败: $mod" }
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git remote add origin $repoUrl
            if ($LASTEXITCODE -ne 0) { throw "git remote add 失败: $mod" }
            git checkout --orphan $stateBranch -q
            if ($LASTEXITCODE -ne 0) { throw "git checkout --orphan 失败: $stateBranch" }

            # 2. 创建只允许 track 对应模块目录的专属白名单 .gitignore
            $gitIgnoreContent = @"
# 仅允许追踪 $mod 模块的状态目录及本配置
/*
!/$mod/
!/$mod/**
!.gitignore
"@
            Set-Content -Path ".gitignore" -Value $gitIgnoreContent -Encoding utf8
            New-Item -ItemType Directory -Force -Path $mod | Out-Null
            New-Item -ItemType File -Force -Path "$mod/.gitkeep" | Out-Null

            git add .gitignore "$mod/.gitkeep"
            if ($LASTEXITCODE -ne 0) { throw "git add 失败: $mod" }
            git commit -m "chore($mod): initialize isolated state branch with exclusive gitignore" -q
            if ($LASTEXITCODE -ne 0) { throw "git commit 失败: $mod" }
            git push -u origin $stateBranch
            if ($LASTEXITCODE -ne 0) { throw "git push 失败: $stateBranch" }

            Write-Host "==> [成功] $stateBranch 已初始化并推送到远端。"
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    if (Test-Path $tempBase) {
        Remove-Item -Recurse -Force $tempBase 2>$null
    }
}

Write-Host "==> 所有指定状态分支检查与初始化已完成！"
