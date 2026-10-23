#!/usr/bin/env python3
"""Run real AppKit buttons against disposable fixtures; needs a --testing build."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'build/arm64/CardDock.app/Contents/MacOS/CardDock'
with tempfile.TemporaryDirectory(prefix='carddock-gui-') as tmp:
    root=Path(tmp); source=root/'Camera Card'; dest=root/'Photo Library'; source.mkdir()
    payloads={'A/IMG.JPG':b'first image fixture','B/IMG.JPG':b'second image fixture','A/ORIGINAL.NEF':b'raw bytes\0'*(1024*600)}
    for name,data in payloads.items():
        p=source/name; p.parent.mkdir(exist_ok=True); p.write_bytes(data); os.utime(p,(1792700000,1792700000))
    def launch(mode,**extra):
        output=ROOT/'work/gui'/extra.pop('label',mode); output.mkdir(parents=True,exist_ok=True)
        config={'source':str(source),'destination':str(dest),'run':mode,**extra}
        env=dict(os.environ,CARDDOCK_TEST_CONFIG=json.dumps(config),CARDDOCK_SCREENSHOTS=str(output))
        p=subprocess.run([str(APP)],env=env,capture_output=True,text=True,timeout=60)
        assert p.returncode==0,p.stderr
        assert 'TEST_EXIT 0 ' in p.stdout,p.stdout+p.stderr
        assert 'Unable to simultaneously satisfy constraints' not in p.stderr,p.stderr
        print(p.stdout.strip())
        return p.stdout
    launch('preview')
    assert not dest.exists(),'Preview wrote to destination'
    launch('import')
    files=[p for p in dest.rglob('*') if p.is_file() and '.carddock' not in p.parts]
    assert len(files)==3
    assert {hashlib.sha256(p.read_bytes()).hexdigest() for p in files}=={hashlib.sha256(b).hexdigest() for b in payloads.values()}
    assert len(list(source.rglob('*.JPG')))==2
    assert '3 duplicates' in launch('import',label='duplicates',appearance='dark',width='minimum')
    launch('import',label='cancel-delete',delete='yes',scope='all',answers='1;cancel')
    assert all((source/n).exists() for n in payloads)
    assert '3 deleted' in launch('import',label='delete',delete='yes',scope='all',answers='1;DELETE')
    assert not any((source/n).exists() for n in payloads)
    assert len(files)==3 and all(p.exists() for p in files)
print('GUI checks passed: read-only preview, real import, exact bytes, duplicate skip, dark/minimum window, cancelled and confirmed deletion.')
