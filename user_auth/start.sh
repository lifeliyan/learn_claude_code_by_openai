#!/bin/bash

# 用户登录系统启动脚本

echo "========================================"
echo "      用户登录系统启动脚本"
echo "========================================"

# 检查Python版本
echo "检查Python版本..."
python3 --version

# 检查依赖
echo "检查依赖..."
if [ ! -f "requirements.txt" ]; then
    echo "错误: requirements.txt 文件不存在"
    exit 1
fi

# 安装依赖（如果venv不存在）
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "使用现有虚拟环境..."
    source venv/bin/activate
fi

# 检查数据库
echo "检查数据库..."
if [ ! -f "users.db" ]; then
    echo "数据库不存在，将在首次运行时自动创建"
fi

# 设置环境变量
export FLASK_APP=app.py
export FLASK_ENV=development

# 生成密钥（如果不存在）
if [ -z "$SECRET_KEY" ]; then
    export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "已生成随机密钥"
fi

# 启动应用
echo "启动应用..."
echo "访问地址: http://localhost:5000"
echo "演示账户: admin / admin123"
echo ""
echo "按 Ctrl+C 停止应用"
echo "========================================"

python3 app.py