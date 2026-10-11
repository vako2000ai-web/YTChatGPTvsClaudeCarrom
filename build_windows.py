"""Reproducible Windows bundle; never collects a real .env or match logs."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--work', type=Path, default=Path('build'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output, work = args.output.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx',
               '--name', 'CarromAIShowdown', '--distpath', str(output), '--workpath', str(work),
               '--specpath', str(work), '--paths', str(root), '--collect-all', 'pygame',
               '--collect-all', 'pymunk', '--hidden-import', '_cffi_backend',
               '--recursive-copy-metadata', 'openai', '--recursive-copy-metadata', 'anthropic',
               '--copy-metadata', 'websocket-client', '--add-data', str(root / 'assets') + ';assets',
               '--exclude-module', 'pytest',
               '--exclude-module', 'tkinter', str(root / 'launcher.py')]
    subprocess.run(command, check=True, cwd=root)
    bundle = output / 'CarromAIShowdown'
    for name in ('.env.example', 'README.md', 'RULES_COVERAGE.md', 'WINDOWS.md', 'Start-Demo.cmd',
                 'Start-API.cmd', 'Record-Demo.cmd', 'Play-Replay.cmd'):
        shutil.copy2(root / name, bundle / name)
    if any(p.name == '.env' for p in bundle.rglob('*')):
        raise RuntimeError('A real .env must not be bundled')
    print(bundle)


if __name__ == '__main__':
    main()
