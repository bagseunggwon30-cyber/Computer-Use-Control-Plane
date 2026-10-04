"""Read-only C# AST source mapping. Windows parser library; no PowerShell process."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
MAX_BYTES=32*1024*1024


def collect(root):
    root=Path(root).resolve()
    for directory in (root/'scripts',root/'tests',root/'tests/fixtures'):
        if directory.exists() and (directory.is_symlink() or getattr(directory.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('Source-map directories must not be links or junctions')
    files=sorted([*(root/'scripts').glob('*.ps1'),*(root/'tests/fixtures').glob('legacy-*-adapter.ps1')])
    if not files or len(files)>1024: raise ValueError('Expected bounded migration source files')
    result=[];total=0
    for path in files:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES:
            raise ValueError('Source map requires bounded ordinary files')
        with path.open('rb') as stream: raw=stream.read(MAX_BYTES+1)
        total+=len(raw)
        if total>MAX_BYTES: raise ValueError('Source-map source exceeds 32 MiB')
        result.append(dict(path=path.relative_to(root).as_posix(),text=raw.decode('utf-8-sig').replace('\r\n','\n')))
    return dict(schema='cucp.source-map-input/v1',files=result)


def source_map(root, executable=None):
    executable=Path(executable or ROOT/'pcucp-next/bin/legacy-syntax/PcuCp.LegacySyntax.exe').absolute()
    if executable.is_symlink() or not executable.is_file(): raise ValueError('Published syntax executable is missing')
    raw=json.dumps(collect(root),ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(raw)>MAX_BYTES: raise ValueError('Source-map request exceeds 32 MiB')
    result=subprocess.run([str(executable)],input=raw,capture_output=True,timeout=30,shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode: raise ValueError('Source-map parser failed: '+result.stderr[:4096].decode('utf-8',errors='replace'))
    if len(result.stdout)>4*1024*1024: raise ValueError('Source-map result exceeds 4 MiB')
    value=json.loads(result.stdout)
    if value.get('schema')!='cucp.migration-source-map/v1' or value.get('encoding')!='utf-8-no-bom-lf':
        raise ValueError('Invalid source-map reply')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--build',action='store_true',help='Explicit source qualification build, never an action-time fallback')
    args=parser.parse_args(argv)
    if args.build:
        if args.executable is not None: raise ValueError('Select either a supplied executable or an explicit source build')
        subprocess.run(['dotnet','build',str(ROOT/'pcucp-next/dotnet/PcuCp.LegacySyntax/PcuCp.LegacySyntax.csproj'),
            '-c','Release','-warnaserror','--nologo'],check=True,timeout=180)
        args.executable=ROOT/'pcucp-next/dotnet/PcuCp.LegacySyntax/bin/Release/net48/PcuCp.LegacySyntax.exe'
    value=source_map(args.root,args.executable)
    args.output.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    print('Mapped '+str(len(value['files']))+' source files without executing their contents.')
    return 0

if __name__=='__main__': raise SystemExit(main())
