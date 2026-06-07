#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RouteMind 一键部署脚本
用法: python deploy.py
然后按提示输入 SSH 密码即可
"""
import fnmatch
import getpass
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

import paramiko

# ============ 配置 ============
HOST = "124.223.28.124"
USER = "root"
REMOTE_DIR = "/opt/routemind"
LOCAL_PROJECT = Path(__file__).parent.resolve()

EXCLUDE = {
    ".env", ".git", ".gitignore", ".tmp_venv", "__pycache__",
    "*.pyc", "*.pyo", "*.log",
    "output/*.log",
    "output/poi_embeddings.npy",
    "output/poi_embedding_ids.json",
    "output/poi_descriptions.json",
    "output/user_memory_profiles.json",
    "ugc_groundtruth_v4_xl.json",
    "screenshot_final.png",
    "take_screenshot.py", "server_launcher.py",
    "web/backup", "tests",
    "_test_*.py", "test_*.py", "test_mimo*.py",
    "generate_*.py", "poi_data",
    "routemind*.tar.gz",
}


def should_exclude(name, relpath):
    for pat in EXCLUDE:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(relpath, pat):
            return True
    return False


def build_package():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pkg_name = f"routemind_{ts}"
    tmp = Path(tempfile.gettempdir()) / pkg_name
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    print("[1/5] 打包项目（自动排除敏感文件）...")
    for root, dirs, files in os.walk(LOCAL_PROJECT):
        rel_root = Path(root).relative_to(LOCAL_PROJECT)
        for f in files:
            rel = str(rel_root / f) if str(rel_root) != "." else f
            if should_exclude(f, rel):
                continue
            src = Path(root) / f
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        # 过滤 dirs 防止遍历被排除的目录
        dirs[:] = [d for d in dirs if not should_exclude(d, str(rel_root / d) if str(rel_root) != "." else d)]

    tar_path = LOCAL_PROJECT / f"{pkg_name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(tmp, arcname=pkg_name)
    shutil.rmtree(tmp)
    size = tar_path.stat().st_size / 1024
    print(f"      包大小: {size:.1f} KB -> {tar_path.name}")
    return tar_path, pkg_name


def ssh_exec(ssh, cmd, sudo=False):
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        for line in out.splitlines()[:30]:
            print(f"    {line}")
    if exit_code != 0 and err:
        for line in err.splitlines()[:10]:
            print(f"    ERR: {line}")
    return exit_code, out, err


def main():
    print("=" * 50)
    print("  RouteMind 一键部署")
    print("=" * 50)
    print()

    # 安全检查
    env_file = LOCAL_PROJECT / ".env"
    if env_file.exists():
        print("[SECURITY] .env 检测到真实 API Key，已自动排除")
        print("           部署后需在服务器上手动创建 .env")
        print()

    # 打包
    tar_path, pkg_name = build_package()

    # 连接
    print()
    print(f"[2/5] 连接服务器 {HOST} ...")
    password = getpass.getpass(f"      请输入 {USER}@{HOST} 的密码: ")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username=USER, password=password, timeout=15)
    except paramiko.AuthenticationException:
        print("[ERROR] 密码错误")
        if tar_path.exists():
            tar_path.unlink()
        return 1
    except Exception as e:
        print(f"[ERROR] 连接失败: {e}")
        if tar_path.exists():
            tar_path.unlink()
        return 1

    # 上传
    print("[3/5] 上传文件...")
    sftp = ssh.open_sftp()
    try:
        sftp.mkdir(REMOTE_DIR)
    except IOError:
        pass
    remote_tar = f"{REMOTE_DIR}/{tar_path.name}"
    sftp.put(str(tar_path), remote_tar)
    sftp.close()
    print(f"      已上传: {remote_tar}")

    # 服务器端配置
    print("[4/5] 服务器端配置...")
    rc, _, _ = ssh_exec(ssh, f"mkdir -p {REMOTE_DIR} && cd {REMOTE_DIR} && tar -xzf {tar_path.name} && rm -rf app && mv {pkg_name} app")
    if rc != 0:
        ssh.close()
        if tar_path.exists():
            tar_path.unlink()
        return 1

    # 检测 Python
    rc, _, _ = ssh_exec(ssh, "python3 --version")
    if rc != 0:
        print("      安装 Python3...")
        ssh_exec(ssh, "apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip")

    # 创建虚拟环境
    venv = f"{REMOTE_DIR}/venv"
    ssh_exec(ssh, f"python3 -m venv {venv} 2>/dev/null || true")
    ssh_exec(ssh, f"{venv}/bin/pip install -q --upgrade pip")

    # 安装依赖
    ssh_exec(ssh, f"{venv}/bin/pip install -q -r {REMOTE_DIR}/app/requirements.txt")

    # 创建 .env（从模板，空 key）
    print("[5/5] 创建环境配置...")
    ssh_exec(ssh, f"cp {REMOTE_DIR}/app/.env.example {REMOTE_DIR}/app/.env 2>/dev/null || true")
    ssh_exec(ssh, f"chmod 600 {REMOTE_DIR}/app/.env")

    # 创建 systemd 服务
    service = f"""[Unit]
Description=RouteMind
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}/app
Environment=PYTHONUNBUFFERED=1
Environment=LOG_FORMAT=json
ExecStart={venv}/bin/python {REMOTE_DIR}/app/web_app.py --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    ssh_exec(ssh, f"cat > /etc/systemd/system/routemind.service <<'EOF'\n{service}\nEOF")
    ssh_exec(ssh, "systemctl daemon-reload && systemctl enable routemind")

    # 防火墙
    ssh_exec(ssh, "ufw allow 8000/tcp 2>/dev/null || true")

    # 启动
    ssh_exec(ssh, "systemctl restart routemind")

    # 验证
    print()
    print("验证服务状态...")
    rc, out, _ = ssh_exec(ssh, "sleep 2 && systemctl is-active routemind && curl -s http://127.0.0.1:8000/api/health")
    ssh.close()

    # 清理本地包
    if tar_path.exists():
        tar_path.unlink()

    print()
    print("=" * 50)
    if rc == 0 and "version" in out:
        print("  ✅ 部署成功")
        print(f"  http://{HOST}:8000")
        print()
        print("  ⚠️  最后一步：SSH 登录服务器填入 API Key")
        print(f"     ssh {USER}@{HOST}")
        print(f"     nano {REMOTE_DIR}/app/.env")
        print("     systemctl restart routemind")
    else:
        print("  ⚠️  服务可能未启动，请检查日志:")
        print(f"     ssh {USER}@{HOST} 'journalctl -u routemind --no-pager -n 30'")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
