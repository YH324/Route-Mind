#!/usr/bin/env bash
# ================================================================
# RouteMind 服务器端一键配置脚本
# 运行环境: Ubuntu 20.04+ / CentOS 7+ (root)
# 安全原则: 绝不读取本地 .env，从模板创建，强制用户填入 Key
# ================================================================
set -euo pipefail

APP_DIR="/opt/routemind"
APP_USER="routemind"
SERVICE_NAME="routemind"
PYTHON_CMD=""

echo "========================================"
echo "  RouteMind 服务器部署脚本"
echo "========================================"

# --- 检测 Python ---
for py in python3.11 python3.10 python3.9 python3.8 python3.7 python3; do
    if command -v "$py" &>/dev/null; then
        PYTHON_CMD="$py"
        break
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    echo "[ERROR] 未检测到 Python 3。正在尝试安装..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-pip python3-venv
        PYTHON_CMD="python3"
    elif command -v yum &>/dev/null; then
        yum install -y python3 python3-pip
        PYTHON_CMD="python3"
    else
        echo "[ERROR] 无法自动安装 Python，请手动安装后重试。"
        exit 1
    fi
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "[INFO] Python 版本: $PY_VERSION"

# --- 创建应用用户 ---
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -s /bin/false -d "$APP_DIR" "$APP_USER"
    echo "[INFO] 创建用户: $APP_USER"
fi

# --- 目录结构 ---
mkdir -p "$APP_DIR"/{app,logs}
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# --- 检查代码包 ---
if [[ ! -d "$APP_DIR/app" ]] || [[ ! -f "$APP_DIR/app/web_app.py" ]]; then
    echo "[ERROR] 未找到应用代码。"
    echo "        请先上传并解压代码到 $APP_DIR/app"
    echo "        示例: scp routemind_*.tar.gz root@host:/opt/routemind/"
    echo "              cd /opt/routemind && tar -xzf routemind_*.tar.gz && mv routemind_* app"
    exit 1
fi

echo "[INFO] 应用目录: $APP_DIR/app"

# --- 创建虚拟环境 ---
VENV_DIR="$APP_DIR/venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "[INFO] 创建虚拟环境..."
    $PYTHON_CMD -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip

# --- 安装依赖 ---
if [[ -f "$APP_DIR/app/requirements.txt" ]]; then
    echo "[INFO] 安装依赖..."
    pip install -q -r "$APP_DIR/app/requirements.txt"
else
    echo "[WARN] 未找到 requirements.txt，仅安装 numpy..."
    pip install -q "numpy>=1.21"
fi

# --- 安全创建 .env ---
ENV_FILE="$APP_DIR/app/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "[SECURITY] 检测到已存在 .env 文件。"
    read -p "         是否覆盖? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "[INFO] 保留现有 .env"
    else
        CREATE_ENV=1
    fi
else
    CREATE_ENV=1
fi

if [[ ${CREATE_ENV:-0} -eq 1 ]]; then
    EXAMPLE="$APP_DIR/app/.env.example"
    if [[ -f "$EXAMPLE" ]]; then
        cp "$EXAMPLE" "$ENV_FILE"
    else
        cat > "$ENV_FILE" <<'EOF'
HOST=127.0.0.1
PORT=8000
SERVER_VERSION=3.3.0
REQUEST_TIMEOUT_SECONDS=90
MAX_REQUEST_BYTES=65536
ENABLE_CORS=1
LOG_LEVEL=INFO

# ===== 必须填入真实 API Key =====
DEEPSEEK_API_KEY=
DEEPSEEK_CHAT_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_AUTH_TYPE=bearer
MIMO_API_KEY=
MINIMAX_API_KEY=
GLM_API_KEY=
EOF
    fi

    echo ""
    echo "========================================"
    echo "  [SECURITY] 请编辑 $ENV_FILE"
    echo "  填入真实的 API Key 后重新加载服务"
    echo "========================================"
    echo ""
    echo "  nano $ENV_FILE"
    echo ""
    echo "  必填项: DEEPSEEK_API_KEY 或其他可用模型服务 Key"
    echo ""
fi

chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# --- 创建 systemd 服务 ---
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=RouteMind Route Planning Service
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/app
Environment=PYTHONUNBUFFERED=1
Environment=LOG_FORMAT=json
ExecStart=$VENV_DIR/bin/python $APP_DIR/app/web_app.py --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=append:$APP_DIR/logs/routemind.log
StandardError=append:$APP_DIR/logs/routemind.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# --- 防火墙（如有 ufw）---
if command -v ufw &>/dev/null; then
    ufw allow 8000/tcp comment 'RouteMind' || true
    echo "[INFO] 已开放 8000 端口 (ufw)"
fi

# --- 启动服务 ---
echo "[INFO] 启动服务..."
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 2

# --- 状态检查 ---
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "========================================"
    echo "  ✅ RouteMind 部署成功"
    echo "========================================"
    echo "  服务状态: $(systemctl is-active $SERVICE_NAME)"
    echo "  监听地址: http://$(curl -s ifconfig.me 2>/dev/null || echo '服务器IP'):8000"
    echo "  日志查看: journalctl -u $SERVICE_NAME -f"
    echo "  管理命令: systemctl {start|stop|restart|status} $SERVICE_NAME"
    echo "========================================"
else
    echo ""
    echo "========================================"
    echo "  ⚠️ 服务启动失败"
    echo "========================================"
    echo "  查看日志: journalctl -u $SERVICE_NAME --no-pager -n 50"
    echo "========================================"
    exit 1
fi
