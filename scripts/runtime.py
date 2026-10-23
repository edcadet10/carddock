#!/usr/bin/env python3
"""Fetch a pinned, SHA-256-checked standalone CPython runtime."""
import hashlib
import pathlib
import sys
import subprocess
import tarfile
import urllib.request

ARCHES = {
    'arm64': ('aarch64', '8dc60610a82f1e73be7faf964383e02520f95f6e39592a5c37c3809f5a7b798e'),
    'x86_64': ('x86_64', 'ce9c748c8f7525c0052247edb2435fdb1cac89c77e687e0e199eaf2b827668c2'),
}
arch = sys.argv[1]
upstream, expected = ARCHES[arch]
root = pathlib.Path(__file__).resolve().parents[1]
cache = root / '.cache'
cache.mkdir(exist_ok=True)
archive = cache / (arch + '.tar.gz')
url = f'https://github.com/astral-sh/python-build-standalone/releases/download/20261021/cpython-3.13.17%2B20261021-{upstream}-apple-darwin-install_only_stripped.tar.gz'
if not archive.exists():
    print('Downloading pinned Python runtime for', arch, flush=True)
    urllib.request.urlretrieve(url, archive)
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    archive.unlink()
    raise SystemExit('Runtime checksum mismatch; archive removed. Run again to retry.')
out = cache / arch
if not (out / 'python' / 'bin' / 'python3').exists():
    out.mkdir(exist_ok=True)
    with tarfile.open(archive) as tf:
        tf.extractall(out, filter='data')
print(out / 'python')

# install_only archives omit the dependency license directory. Preserve it from
# the matching, independently checksum-verified full distribution.
full_hash = {
    'arm64': '3ccb423f96990a6ac6a10e23052ba6c70144117559af097cd0c0305939dc015b',
    'x86_64': '174c738acbf8b768c96c8b1f4e4b40f8d7a04059192360a920fe8c305154bbc8',
}[arch]
full = cache / (arch + '-full.tar.zst')
if not (out / 'python' / 'licenses').exists():
    if not full.exists():
        urllib.request.urlretrieve(f'https://github.com/astral-sh/python-build-standalone/releases/download/20261021/cpython-3.13.17%2B20261021-{upstream}-apple-darwin-pgo%2Blto-full.tar.zst', full)
    if hashlib.sha256(full.read_bytes()).hexdigest() != full_hash:
        full.unlink()
        raise SystemExit('Full runtime checksum mismatch.')
    subprocess.run(['/usr/bin/tar', '-xf', str(full), '-C', str(out), 'python/licenses', 'python/PYTHON.json'], check=True)
