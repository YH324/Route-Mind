#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RouteMind 本地打包脚本
安全原则：.env 文件绝不包含在部署包中
"""
import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SERVER_HOST = "47.102.142.207"
SERVER_USER = "root"
REMOTE_PATH = "/opt/routemind"

EXCLUDE_PATTERNS = {
    ".env", ".git", ".gitignore", ".tmp_venv", "__pycache__",
    "*.pyc", "*.pyo", "*.log",
    "output/*.log",
    "output/poi_embeddings.npy",
    "output/poi_embedding_ids.json",
    "output/poi_descriptions.json",
    "output/user_memory_profiles.json",
    "ugc_groundtruth_v4_xl.json",
    "screenshot*.png",
    "routemind*.tar.gz",
    "take_screenshot.py", "server_launcher.py",
    "web/backup", "tests",
    "_test_*.py", "test_*.py", "test_mimo*.py",
    "generate_*.py", "poi_data",
}


def match_any(name, relpath, patterns):
    import fnmatch
    for p in patterns:
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(relpath, p):
            return True
    return False


def copy_filtered(src: Path, dst: Path, rel: str = ""):
    for child in src.iterdir():
        child_rel = f"{rel}/{child.name}" if rel else child.name
        if match_any(child.name, child_rel, EXCLUDE_PATTERNS):
            print(f"  SKIP {child_rel}")
            continue
        child_dst = dst / child.name
        if child.is_dir():
            child_dst.mkdir(parents=True, exist_ok=True)
            copy_filtered(child, child_dst, child_rel)
        else:
            shutil.copy2(child, child_dst)


def main():
    out_file = sys.argv[1] if len(sys.argv) > 1 else None

    # 安全检查
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        print("[SECURITY] 检测到 .env 文件包含真实 API Key。")
        print("           该文件已被自动排除，不会进入部署包。")
        print("           服务器上需手动创建 .env（参见 DEPLOY.md）。")
        print()

    # 创建临时目录
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pkg_name = f"routemind_{ts}"
    temp_dir = Path(os.environ.get("TEMP", "/tmp")) / pkg_name
    pkg_file = Path(out_file) if out_file else (temp_dir.parent / f"{pkg_name}.tar.gz")

    print(f"[PACK] 创建临时目录: {temp_dir}")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    print("[PACK] 复制项目文件...")
    copy_filtered(PROJECT_ROOT, temp_dir)

    print(f"[PACK] 打包: {pkg_file}")
    pkg_file.parent.mkdir(parents=True, exist_ok=True)
    if pkg_file.exists():
        pkg_file.unlink()
    with tarfile.open(pkg_file, "w:gz") as tar:
        tar.add(temp_dir, arcname=pkg_name)

    size_kb = pkg_file.stat().st_size / 1024
    print(f"[PACK] 完成。包大小: {size_kb:.1f} KB")
    print(f"       路径: {pkg_file}")
    print()

    # 输出上传命令
    print("=" * 40)
    print("  下一步：上传到服务器")
    print("=" * 40)
    print()
    print("在 PowerShell / Git Bash 中执行:")
    print()
    print(f"  scp \"{pkg_file}\" {SERVER_USER}@{SERVER_HOST}:{REMOTE_PATH}/")
    print()
    print("然后在服务器上执行:")
    print()
    pkg_leaf = pkg_file.name
    print(f"  cd {REMOTE_PATH} && tar -xzf {pkg_leaf} && rm -rf app && mv {pkg_name} app")
    print()
    print("最后运行 server_setup.sh 完成配置。")
    print()


if __name__ == "__main__":
    main()
