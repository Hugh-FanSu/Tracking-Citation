"""Create a local macOS launcher using the currently installed Python environment."""
import plistlib
from pathlib import Path
import shlex
import sys
from . import __version__


def install_app(destination, working_directory=None):
    if sys.platform!='darwin':raise ValueError('This .app launcher is for macOS; other systems can use paper-citations-gui')
    destination=Path(destination).expanduser().resolve()
    if destination.suffix!='.app':raise ValueError('Destination must end with .app')
    if destination.exists():raise FileExistsError(destination)
    working=Path(working_directory or destination.parent).resolve()
    binary=destination/'Contents/MacOS';binary.mkdir(parents=True)
    info={'CFBundleName':'论文引用解析','CFBundleDisplayName':'论文引用解析','CFBundleIdentifier':'local.paper-citations.desktop',
          'CFBundleVersion':__version__,'CFBundleShortVersionString':__version__,'CFBundleExecutable':'launcher','CFBundlePackageType':'APPL',
          'NSHighResolutionCapable':True}
    with (destination/'Contents/Info.plist').open('wb') as f:plistlib.dump(info,f)
    log=working/'paper-citations-gui.log'
    command='#!/bin/zsh\ncd '+shlex.quote(str(working))+'\nexec '+shlex.quote(sys.executable)+' -m paper_citation_pipeline.gui >> '+shlex.quote(str(log))+' 2>&1\n'
    launcher=binary/'launcher';launcher.write_text(command,encoding='utf-8');launcher.chmod(0o755)
    return destination
