# RouteMind 智行策 生产部署指南

> 安全原则：`.env` 文件（含真实 API Key）**绝不进入代码仓库或部署包**。服务器上独立创建。

---

## 1. 安全检查

```powershell
cd /path/to/routemind

# 确认 .env 未被 git 跟踪
git ls-files | findstr "\.env"
# 预期：无输出（表示 .env 未被跟踪）

# 确认 git 历史中无 API Key
git log --all -p -S "sk-" -- "*.py" "*.md" "*.txt"
# 预期：无输出
```

---

## 2. 打包

```powershell
cd /path/to/routemind/deploy
.\local_deploy.ps1
```

脚本会自动：
- ✅ 排除 `.env` / `__pycache__` / `.git` / `.tmp_venv` 等
- ✅ 生成 `routemind_*.tar.gz` 到 `%TEMP%`
- ✅ 输出 `scp` 上传命令

也可以使用 Python 打包脚本：

```powershell
cd /path/to/routemind
python deploy\local_deploy.py
```

如果本机已安装 `paramiko`，还可以使用交互式一键部署：

```powershell
python -m pip install paramiko
python deploy.py
```

`deploy.py` 会要求输入服务器 SSH 密码，自动上传、安装依赖、创建 systemd 服务并做健康检查。真实 API Key 仍然不会写入包内，需要部署后在服务器 `.env` 中填写。

---

## 3. 上传到服务器

```bash
# 在 PowerShell 或 Git Bash 中执行
scp %TEMP%\routemind_20260606_xxxxxx.tar.gz root@47.102.142.207:/opt/routemind/
```

> 提示输入密码时，输入服务器 root 密码。

---

## 4. 服务器端配置（SSH 登录后执行）

```bash
ssh root@47.102.142.207

# 创建目录并解压
mkdir -p /opt/routemind
cd /opt/routemind
tar -xzf routemind_*.tar.gz
rm -rf app
mv routemind_* app

# 运行一键配置脚本
cd app
chmod +x deploy/server_setup.sh
./deploy/server_setup.sh
```

脚本会：
1. 检测/安装 Python 3.7+
2. 创建虚拟环境并安装依赖
3. 从 `.env.example` 创建安全的 `.env`
4. 创建 `routemind` systemd 服务
5. 开放 8000 端口

---

## 5. 填入 API Key（关键步骤）

```bash
nano /opt/routemind/app/.env
```

修改以下行，填入真实 Key：

```ini
MINIMAX_API_KEY=your_minimax_key_here
GLM_API_KEY=your_glm_key_here
```

> MiMo 当前已禁用，可不填。

保存后重启服务：

```bash
systemctl restart routemind
systemctl status routemind
```

---

## 6. 验证

```bash
# 本地健康检查
curl http://47.102.142.207:8000/api/health

# 验证规划接口
curl -X POST http://47.102.142.207:8000/api/v2/plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"春熙路附近，下午四点想吃火锅","city":"成都","mode":"tourist"}'
```

---

## 7. 日常管理

| 操作 | 命令 |
|------|------|
| 查看状态 | `systemctl status routemind` |
| 查看日志 | `journalctl -u routemind -f` |
| 重启服务 | `systemctl restart routemind` |
| 停止服务 | `systemctl stop routemind` |
| 更新代码 | 重新执行步骤 2-4，然后 `systemctl restart routemind` |

---

## 8. 安全清单

- [ ] `.env` 文件权限为 `600`（仅所有者可读写）
- [ ] `.env` 不在 git 跟踪中
- [ ] git 历史中没有硬编码的 API Key
- [ ] 服务器防火墙仅开放必要端口
- [ ] 生产环境建议使用 Nginx 反向代理 + HTTPS
- [ ] 建议使用 `HOST=127.0.0.1` 配合 Nginx / Caddy 转发，避免直接暴露应用端口
