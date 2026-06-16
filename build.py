#!/usr/bin/env python3
import os, sys, shutil, subprocess, platform
from pathlib import Path

name = 'BadmintonAnnotatorV2.1.2'
              # 最终可执行文件的名字
ENTRY = 'main.py'              # 你的入口脚本
ONE_DIR = False                # True=单文件夹, False=单文件
YOLO_MODEL = Path('ai') / 'models' / 'yolov8n.onnx'
MIN_OPENCV_VERSION = (4, 11, 0)

def run(cmd):
    print('>>>', cmd)
    ret = subprocess.run(cmd)
    if ret.returncode:
        sys.exit(ret.returncode)


def parse_version(version):
    parts = []
    for token in version.split('.')[:3]:
        try:
            parts.append(int(token))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check_build_requirements():
    if not YOLO_MODEL.exists():
        raise SystemExit(f"缺少默认 YOLO 模型，无法打包: {YOLO_MODEL}")
    try:
        import cv2
    except Exception as exc:
        raise SystemExit(f"缺少 OpenCV，无法打包: {exc}") from exc
    version = parse_version(cv2.__version__)
    if version < MIN_OPENCV_VERSION:
        required = '.'.join(str(part) for part in MIN_OPENCV_VERSION)
        raise SystemExit(
            f"OpenCV 版本过低: {cv2.__version__}。YOLO 需要 {required}+，"
            "请先更新 Label_env 再打包。"
        )


def build():
    check_build_requirements()
    cmd = [sys.executable, '-m', 'PyInstaller',
           '--name', name,
           '--clean', '--noconfirm',
           '--distpath', 'dist',
           '--workpath', 'build',
           '--specpath', '.',
           '--onefile' if not ONE_DIR else '--onedir']
    # macOS 加 .app 包
    if platform.system() == 'Darwin' or platform.system() == 'Windows':
        cmd += ['--windowed']          # 无控制台
    data_separator = ';' if platform.system() == 'Windows' else ':'
    cmd += ['--add-data', f'{YOLO_MODEL}{data_separator}ai/models']
    cmd += [ENTRY]
    run(cmd)

    # 可选：把产物统一放进 release/ 方便上传
    os.makedirs('release', exist_ok=True)
    src = f'dist/{name}{".exe" if platform.system()=="Windows" else ""}'
    dst = f'release/{name}-{platform.system()}-{platform.machine()}'
    shutil.move(src, dst)
    print('打包完成:', dst)

if __name__ == '__main__':
    build()
