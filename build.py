#!/usr/bin/env python3
import os, sys, shutil, subprocess, platform

NAME = 'BadmintonAnnotatorV2.0'                # 最终可执行文件的名字
ENTRY = 'main.py'              # 你的入口脚本
ONE_DIR = False                # True=单文件夹, False=单文件

def run(cmd):
    print('>>>', cmd)
    ret = subprocess.run(cmd, shell=True)
    if ret.returncode:
        sys.exit(ret.returncode)

def build():
    cmd = [sys.executable, '-m', 'PyInstaller',
           '--name', NAME,
           '--clean', '--noconfirm',
           '--distpath', 'dist',
           '--workpath', 'build',
           '--specpath', '.',
           '--onefile' if not ONE_DIR else '--onedir']
    # macOS 加 .app 包
    if platform.system() == 'Darwin':
        cmd += ['--windowed']          # 无控制台
    cmd += [ENTRY]
    run(' '.join(cmd))

    # 可选：把产物统一放进 release/ 方便上传
    os.makedirs('release', exist_ok=True)
    src = f'dist/{NAME}{".exe" if platform.system()=="Windows" else ""}'
    dst = f'release/{NAME}-{platform.system()}-{platform.machine()}'
    shutil.move(src, dst)
    print('打包完成:', dst)

if __name__ == '__main__':
    build()
