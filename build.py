#!/usr/bin/env python3
import os, sys, shutil, subprocess, platform, stat
from pathlib import Path

name = 'BadmintonAnnotatorV2.1.2'
              # 最终可执行文件的名字
ENTRY = 'main.py'              # 你的入口脚本
ONE_DIR = False                # True=单文件夹, False=单文件
YOLO_MODEL = Path('ai') / 'models' / 'yolov8n.onnx'
MIN_OPENCV_VERSION = (4, 11, 0)
DIST_DIR = Path('dist')
BUILD_DIR = Path('build')
RELEASE_DIR = Path('release')
MACOS_BUNDLE_ID = os.environ.get('MACOS_BUNDLE_ID', 'com.gang.badmintonannotator')

def run(cmd):
    print('>>>', cmd)
    ret = subprocess.run(cmd)
    if ret.returncode:
        sys.exit(ret.returncode)


def run_if_available(cmd):
    if not shutil.which(cmd[0]):
        print(f"跳过，未找到命令: {cmd[0]}")
        return
    run(cmd)


def run_diagnostic(cmd):
    if not shutil.which(cmd[0]):
        print(f"跳过诊断，未找到命令: {cmd[0]}")
        return
    print('>>>', cmd)
    subprocess.run(cmd)


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
    system = platform.system()
    package_mode = '--onedir' if system == 'Darwin' or ONE_DIR else '--onefile'
    cmd = [sys.executable, '-m', 'PyInstaller',
           '--name', name,
           '--clean', '--noconfirm',
           '--distpath', str(DIST_DIR),
           '--workpath', str(BUILD_DIR),
           '--specpath', '.',
           package_mode]
    # macOS 加 .app 包
    if system == 'Darwin' or system == 'Windows':
        cmd += ['--windowed']          # 无控制台
    if system == 'Darwin':
        cmd += ['--osx-bundle-identifier', MACOS_BUNDLE_ID]
        target_arch = os.environ.get('MACOS_TARGET_ARCH')
        if target_arch:
            cmd += ['--target-arch', target_arch]
    data_separator = ';' if platform.system() == 'Windows' else ':'
    cmd += ['--add-data', f'{YOLO_MODEL}{data_separator}ai/models']
    cmd += [ENTRY]
    run(cmd)

    package_release(system)


def package_release(system):
    RELEASE_DIR.mkdir(exist_ok=True)
    product = find_pyinstaller_product(system)
    arch = os.environ.get('MACOS_TARGET_ARCH') if system == 'Darwin' else None
    arch = arch or platform.machine()
    release_stem = f'{name}-{system}-{arch}'

    if system == 'Darwin':
        prepare_macos_product(product)
        zip_path = RELEASE_DIR / f'{release_stem}.zip'
        remove_path(zip_path)
        run_if_available(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(product), str(zip_path)])
        if zip_path.exists():
            print('macOS 分发包:', zip_path)
            print('对方若仍被系统拦截，可让其执行:')
            print(f'  xattr -dr com.apple.quarantine "{product.name}"')
            return

    release_product = RELEASE_DIR / release_stem
    if product.suffix:
        release_product = release_product.with_suffix(product.suffix)
    remove_path(release_product)
    shutil.move(str(product), str(release_product))
    if system != 'Windows' and release_product.is_file():
        make_executable(release_product)
    print('打包完成:', release_product)


def find_pyinstaller_product(system):
    candidates = []
    if system == 'Darwin':
        candidates.extend([DIST_DIR / f'{name}.app', DIST_DIR / name])
    elif system == 'Windows':
        candidates.extend([DIST_DIR / f'{name}.exe', DIST_DIR / name])
    else:
        candidates.append(DIST_DIR / name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit(f"未找到 PyInstaller 产物，已检查: {[str(p) for p in candidates]}")


def prepare_macos_product(product):
    executable = product
    if product.suffix == '.app':
        executable = product / 'Contents' / 'MacOS' / name
    if executable.exists() and executable.is_file():
        make_executable(executable)
    run_diagnostic(['xattr', '-dr', 'com.apple.quarantine', str(product)])
    run_if_available(['codesign', '--force', '--deep', '--sign', '-', str(product)])
    run_if_available(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(product)])
    run_diagnostic(['spctl', '-a', '-vv', str(product)])


def make_executable(path):
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def remove_path(path):
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()

if __name__ == '__main__':
    build()
