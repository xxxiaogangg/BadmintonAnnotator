import os
import sys
import shutil
import subprocess
import platform

NAME = 'BadmintonAnnotatorV2.1.7'
ENTRY = 'main.py'
ONE_DIR = False  # 注意：在 --windowed 模式下，macOS 仍会生成 .app 文件夹

def run(cmd):
    print('>>>', cmd)
    ret = subprocess.run(cmd, shell=True)
    if ret.returncode:
        sys.exit(ret.returncode)

def _post_process(name, windowed):
    system = platform.system()
    os.makedirs('release', exist_ok=True)

    if system == 'Darwin':
        src_app = os.path.join('dist', f'{name}.app')
        src_bin = os.path.join('dist', name)
        if windowed and os.path.exists(src_app):
            dst_base = f'release/{name}-macOS-{platform.machine()}'
            print(f'正在压缩 {src_app} 为 zip...')
            shutil.make_archive(dst_base, 'zip', root_dir='dist', base_dir=f'{name}.app')
            print(f'打包完成: {dst_base}.zip')
        elif os.path.exists(src_bin):
            dst_bin = os.path.join('release', f'{name}-macOS-{platform.machine()}')
            shutil.move(src_bin, dst_bin)
            print(f'打包完成: {dst_bin}')
        else:
            print(f'错误: 未找到产物 {src_app} 或 {src_bin}')

    elif system == 'Windows':
        src_exe = os.path.join('dist', f'{name}.exe')
        dst_exe = os.path.join('release', f'{name}-Windows-{platform.machine()}.exe')
        if os.path.exists(src_exe):
            shutil.move(src_exe, dst_exe)
            print(f'打包完成: {dst_exe}')
        else:
            print(f'错误: 未找到产物 {src_exe}')

    else:
        # Linux / other
        src_bin = os.path.join('dist', name)
        dst_bin = os.path.join('release', f'{name}-Linux-{platform.machine()}')
        if os.path.exists(src_bin):
            shutil.move(src_bin, dst_bin)
            print(f'打包完成: {dst_bin}')
        else:
            print(f'错误: 未找到产物 {src_bin}')


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
    _post_process(NAME, windowed=True)


def build_console():
    """
    构建保留命令行窗口的版本（用于排查崩溃日志）。
    仅影响 Windows/Linux，macOS 仍生成 .app。
    """
    console_name = f'{NAME}-console'
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', console_name,
        '--clean', '--noconfirm',
        '--distpath', 'dist',
        '--onefile' if not ONE_DIR else '--onedir',
        ENTRY
    ]
    run(' '.join(cmd))
    _post_process(console_name, windowed=False)

if __name__ == '__main__':
    # 默认仍是无控制台版本
    if '--console' in sys.argv:
        build_console()
    else:
        build()
