#!/usr/bin/env bash
# 一键初始化并推送各智能体纯净的状态孤儿分支 (state/*)
set -euo pipefail

DEFAULT_MODULES=("market-fx" "paper-agent" "world-news" "reviewer-radar")
MODULES=("${@:-${DEFAULT_MODULES[@]}}")

CURRENT_BRANCH=$(git branch --show-current)

for mod in "${MODULES[@]}"; do
  state_branch="state/${mod}"
  temp_branch="orphan-init-${mod}-$$"

  echo "==> 正在初始化孤儿分支: ${state_branch}..."
  git checkout --orphan "${temp_branch}" > /dev/null 2>&1
  git rm -rf . > /dev/null 2>&1 || true

  mkdir -p "${mod}"
  cat <<EOF > "${mod}/history.json"
{
  "version": 1,
  "initialized_at": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
}
EOF

  git add -f "${mod}/history.json"
  git commit -m "chore(${mod}): initialize clean orphan state branch" > /dev/null 2>&1
  git push -f origin "${temp_branch}:${state_branch}"

  git checkout "${CURRENT_BRANCH}" > /dev/null 2>&1
  git branch -D "${temp_branch}" > /dev/null 2>&1
  echo "==> ${state_branch} 初始化并推送成功。"
done

echo "==> 所有指定的状态分支已全部初始化完毕！"
