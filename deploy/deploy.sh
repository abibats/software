#!/bin/bash
# 华为云 ECS 部署脚本
# 使用方法：在 ECS 上执行 bash deploy.sh

set -e

APP_DIR="${APP_DIR:-/opt/study-seat}"
REPO_URL="${REPO_URL:-https://github.com/abibats/software.git}"
BRANCH="${BRANCH:-main}"

echo "=== 自习座位预约系统部署 ==="

# 1. 安装依赖（仅首次）
if ! command -v python3 &>/dev/null; then
    echo "安装 Python3..."
    sudo yum install -y python3
fi

# 2. 克隆或更新代码
if [ -d "$APP_DIR/.git" ]; then
    echo "更新代码..."
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    echo "克隆代码..."
    sudo mkdir -p "$APP_DIR"
    sudo chown "$(whoami)" "$APP_DIR"
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. 运行测试
echo "运行自动化测试..."
cd backend
python3 -m unittest discover -s . -p "test_*.py" -v
if [ $? -ne 0 ]; then
    echo "测试失败，终止部署"
    exit 1
fi
echo "测试通过"

# 4. 重启服务
echo "重启服务..."
sudo systemctl restart study-seat
sleep 2

# 5. 健康检查
echo "健康检查..."
for i in $(seq 1 10); do
    if curl -s http://127.0.0.1:8000/api/health | grep -q "ok"; then
        echo "部署成功，服务运行正常"
        exit 0
    fi
    sleep 1
done

echo "健康检查失败，请手动排查"
exit 1
