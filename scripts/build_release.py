"""Build portable source/wheel and installer bundles; never include project data."""
from pathlib import Path
import hashlib
import subprocess
import sys
import tomllib
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    out = root / 'release' / version
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'build', '--outdir', str(out)], cwd=root, check=True)
    wheel = out / f'paper_citation_pipeline-{version}-py3-none-any.whl'
    assets = [wheel, out / f'paper_citation_pipeline-{version}.tar.gz']
    resources = [p for folder in ('templates', 'docs', 'examples') for p in (root / folder).rglob('*') if p.is_file() and p.suffix in ('.md', '.mmd', '.json', '.csv', '.xlsx')]
    for platform, launcher in [('macOS', 'Install-macOS.command'), ('Windows', 'Install-Windows.cmd')]:
        archive = out / f'Tracking-Citation-{version}-{platform}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(wheel, wheel.name)
            for name in ('install.py', launcher):
                z.write(root / 'installers' / name, name)
            for p in resources + [root / 'README.md', root / 'compose.yaml']:
                z.write(p, p.relative_to(root))
        assets.append(archive)
    archive = out / f'Tracking-Citation-{version}-templates.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in resources:
            if p.is_relative_to(root / 'templates'):
                z.write(p, p.relative_to(root))
    assets.append(archive)
    (out / 'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in assets))
    print('Release assets:', out)


if __name__ == '__main__':
    main()
