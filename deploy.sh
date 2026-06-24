#!/usr/bin/env bash
# ============================================
#  资源站一键部署脚本
#  用法: ./deploy.sh "更新说明"
# ============================================
set -euo pipefail

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

COMMIT_MSG="${1:-更新资源}"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  资源站部署脚本${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 1. 检查是否有未提交的更改
echo -e "${YELLOW}[1/5]${NC} 检查 Git 状态..."
if [[ -z $(git status --porcelain) ]] && [[ "$COMMIT_MSG" == "更新资源" ]]; then
  echo -e "${YELLOW}  ⚠ 没有检测到更改，但继续执行...${NC}"
fi

# 2. 安装依赖
echo -e "${YELLOW}[2/5]${NC} 检查依赖..."
if [[ ! -d "node_modules" ]]; then
  echo "  正在安装依赖..."
  npm install
else
  echo -e "  ${GREEN}✓${NC} 依赖已就绪"
fi

# 3. 构建
echo -e "${YELLOW}[3/5]${NC} 构建静态网站..."
npm run build
echo -e "  ${GREEN}✓${NC} 构建完成 → .vitepress/dist/"

# 4. Git 操作
echo -e "${YELLOW}[4/5]${NC} Git 提交与推送..."
git add -A
git diff --cached --quiet && git diff --quiet && {
  echo -e "  ${YELLOW}⚠ 没有需要提交的更改${NC}"
} || {
  git commit -m "$COMMIT_MSG"
  echo -e "  ${GREEN}✓${NC} 已提交: $COMMIT_MSG"
}

# 推送
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "  推送到 origin/$BRANCH ..."
git push origin "$BRANCH"
echo -e "  ${GREEN}✓${NC} 推送成功"

# 5. 完成
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✅ 部署完成！${NC}"
echo ""
echo -e "  🌐 网站地址: ${BLUE}https://aitop233.github.io${NC}"
echo -e "  🔧 源码仓库: ${BLUE}https://github.com/AiTop233/AiTop233.github.io${NC}"
echo ""
echo -e "  ⏱ GitHub Actions 正在自动部署，稍等 1-2 分钟即可刷新看到更新。"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
