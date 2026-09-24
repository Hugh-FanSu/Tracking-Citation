"""Install/update this release into a user-local Python environment."""
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Please install Python 3.12 with Tk support first.')
    root = Path(__file__).resolve().parent
    wheels = list(root.glob('paper_citation_pipeline-*.whl'))
    if len(wheels) != 1:
        raise SystemExit('Expected exactly one release wheel beside install.py.')
    base = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Tracking-Citation'
    env = base / 'runtime'
    venv.EnvBuilder(with_pip=True).create(env)
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '--upgrade', str(wheels[0]) + '[full]'], check=True)
    subprocess.run([str(python), '-c', 'import tkinter'], check=True)
    if sys.platform == 'darwin':
        launcher = base / 'Tracking Citation.app'
        if not launcher.exists():
            subprocess.run([str(python), '-m', 'paper_citation_pipeline', 'install-gui', str(launcher)], check=True)
        subprocess.run(['open', str(launcher)], check=True)
    elif os.name == 'nt':
        pythonw = env / 'Scripts/pythonw.exe'
        def quote(s): return "'" + str(s).replace("'", "''") + "'"
        script = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut(' + quote(base / 'Tracking Citation.lnk') + ');'
                  '$s.TargetPath=' + quote(pythonw) + ';$s.Arguments="-m paper_citation_pipeline.gui";'
                  '$s.WorkingDirectory=' + quote(base) + ';$s.Save()')
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], check=True)
        subprocess.Popen([str(pythonw), '-m', 'paper_citation_pipeline.gui'], cwd=base)
    print('Installed. Launcher location:', base)


if __name__ == '__main__':
    main()
