"""Freeze all project-owned code/test/config inputs without credential contents."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
PREFIXES=('src/','tests/','simulation/','scripts/','configs/')
FILES={'pyproject.toml','requirements-vision.txt','AGENTS.md','Vehicle_Autonomy_V1.0.md','Vehicle_Autonomy_File_Structure_V1.1.md'}


def current():
    names=subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    files={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(set(names)) if name and (name.startswith(PREFIXES) or name in FILES) and (ROOT/name).is_file()}
    return dict(schema=1,head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),files=files)


def freeze(path):
    value=current();value['working_tree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT))
    encoded=json.dumps(value,sort_keys=True,indent=2)+'\n'
    with Path(path).open('x') as file:file.write(encoded)
    return hashlib.sha256(encoded.encode()).hexdigest()


def unchanged(path):
    original=json.loads(Path(path).read_text());now=current()
    return original['head']==now['head'] and original['files']==now['files']
