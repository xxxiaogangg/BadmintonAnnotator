import os
import sys
import shutil
import subprocess
import platform

NAME = 'BadmintonAnnotatorV2.1.2'
ENTRY = 'main.py'
ONE_DIR = False  # 注意：在 --windowed 模式下，macOS 仍会生成 .app 文件夹

def run(cmd):
    print('>>>', cmd)
    ret = subprocess.run(cmd, shell=True)
    if ret.returncode:
        sys.exit(ret.returncode)

def build():
    # 1. 基础打包命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', NAME,
        '--clean', '--noconfirm',
        '--windowed',  # 必须开启，以生成 .app
        '--distpath', 'dist',
        '--onefile' if not ONE_DIR else '--onedir',
        ENTRY
    ]
    run(' '.join(cmd))

    # 2. 产物路径识别与处理
    system = platform.system()
    os.makedirs('release', exist_ok=True)

    if system == 'Darwin':
        # macOS 处理逻辑
        src_app = os.path.join('dist', f'{NAME}.app')
        dst_base = f'release/{NAME}-macOS-{platform.machine()}'
        
        if os.path.exists(src_app):
            print(f'正在压缩 {src_app} 为 zip...')
            # make_archive 会自动加上 .zip 后缀
            # base_name: 压缩包路径, format: 'zip', root_dir: 包含要压缩内容的目录, base_dir: 目录内要压缩的文件夹名
            shutil.make_archive(dst_base, 'zip', root_dir='dist', base_dir=f'{NAME}.app')
            print(f'打包完成: {dst_base}.zip')
        else:
            print(f'错误: 未找到产物 {src_app}')

    elif system == 'Windows':
        # Windows 处理逻辑
        src_exe = os.path.join('dist', f'{NAME}.exe')
        dst_exe = os.path.join('release', f'{NAME}-Windows-{platform.machine()}.exe')
        if os.path.exists(src_exe):
            shutil.move(src_exe, dst_exe)
            print(f'打包完成: {dst_exe}')

if __name__ == '__main__':
    build()