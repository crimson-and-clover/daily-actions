#!/usr/bin/env bash
# 一键安全初始化各智能体状态孤儿分支 (state/*)
# 原则：
# 1. 先检查远端是否已存在该分支，存在则跳过，绝不覆盖已有状态；
# 2. 全程在系统临时目录 (mktemp) 下独立操作，绝不影响当前主仓库工作区；
# 3. 根目录仅放置专属 .gitignore（白名单模式只允许 track 该模块自身目录），不预置业务数据文件。

set -euo pipefail

DEFAULT_MODULES=("market-fx" "paper-agent" "world-news" "reviewer-radar")
MODULES=("${@:-${DEFAULT_MODULES[@]}}")

REPO_URL=$(git remote get-url origin 2>/dev/null || true)
if [ -z "${REPO_URL}" ]; then
  echo "错误: 未找到远程仓库 origin 地址" >&2
  exit 1
fi

TMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t "state_init")
trap 'rm -rf "${TMP_DIR}"' EXIT

for mod in "${MODULES[@]}"; do
  state_branch="state/${mod}"

  # 1. 检查远端是否已存在该状态分支
  if git ls-remote --exit-code --heads origin "${state_branch}" >/dev/null 2>&1; then
    echo "[跳过] 远端已存在 ${state_branch} 分支，保留既有历史状态。"
    continue
  fi

  echo "==> [初始化] 远端不存在 ${state_branch}，正在安全创建..."

  WORK_DIR="${TMP_DIR}/${mod}"
  mkdir -p "${WORK_DIR}"
  pushd "${WORK_DIR}" > /dev/null

  git init -q
  git config user.name "$(git -C "${OLDPWD}" config user.name 2>/dev/null || echo 'github-actions[bot]')"
  git config user.email "$(git -C "${OLDPWD}" config user.email 2>/dev/null || echo '41898282+github-actions[bot]@users.noreply.github.com')"
  git remote add origin "${REPO_URL}"
  git checkout --orphan "${state_branch}" -q

  # 2. 创建只允许 track 对应模块目录的专属白名单 .gitignore
  cat <<EOF > .gitignore
# 仅允许追踪 ${mod} 模块的状态目录及本配置
/*
!/${mod}/
!/${mod}/**
!.gitignore
EOF

  mkdir -p "${mod}"
  touch "${mod}/.gitkeep"

  git add .gitignore "${mod}/.gitkeep"
  git commit -m "chore(${mod}): initialize isolated state branch with exclusive gitignore" -q
  git push -u origin "${state_branch}"

  popd > /dev/null
  echo "==> [成功] ${state_branch} 已初始化并推送到远端。"
done

echo "==> 所有指定状态分支检查与初始化已完成！"
