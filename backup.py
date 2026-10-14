"""Consistent SQLite/original-file backups. Keys are never included in archives."""
import argparse
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
import portalocker
from app.core.config import Settings
from app.storage.database import Database


def backup(settings, output):
    db=Database(settings)
    db.initialize()
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise ValueError('Backup output already exists')
    with portalocker.Lock(str(db.path)+'.files.lock',timeout=30), tempfile.TemporaryDirectory() as temp:
        snapshot=Path(temp)/'library.db'
        with db.connect() as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        with sqlite3.connect(snapshot) as conn:
            files=[row[0] for row in conn.execute("SELECT storage_name FROM documents WHERE storage_name!=''")]
            files += [row[0]+'.part' for row in conn.execute('SELECT id FROM uploads WHERE offset>0')]
        try:
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot,'library.db')
                for name in files:
                    if Path(name).name != name:
                        raise ValueError('Invalid stored filename')
                    archive.write(settings.upload_dir/name,'uploads/'+name)
                archive.writestr('manifest.json',json.dumps({'format':1,'encrypted':bool(settings.encryption_key),'files':files}))
            output.chmod(0o600)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return output


def restore(archive_path, destination):
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Restore destination must be empty')
    with zipfile.ZipFile(archive_path) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!=1:
            raise ValueError('Unsupported backup format')
        allowed={'library.db','manifest.json'} | {'uploads/'+name for name in manifest['files'] if Path(name).name==name}
        if set(archive.namelist())!=allowed or len(archive.namelist())!=len(allowed):
            raise ValueError('Unexpected or unsafe archive entries')
        destination.mkdir(parents=True,exist_ok=True,mode=0o700)
        for name in allowed-{'manifest.json'}:
            target=destination/('syllabus.db' if name=='library.db' else name)
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with archive.open(name) as source,target.open('wb') as stream:
                import shutil
                shutil.copyfileobj(source,stream)
            target.chmod(0o600)
    with sqlite3.connect(destination/'syllabus.db') as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Restored database failed integrity check')
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('create');create.add_argument('output',type=Path)
    recover=sub.add_parser('restore');recover.add_argument('archive',type=Path);recover.add_argument('destination',type=Path)
    args=parser.parse_args()
    try:
        result=backup(Settings(),args.output) if args.command=='create' else restore(args.archive,args.destination)
    except (ValueError,OSError,sqlite3.Error,zipfile.BadZipFile) as exc:
        parser.exit(1,f'Backup operation failed: {exc}\n')
    print(result)
