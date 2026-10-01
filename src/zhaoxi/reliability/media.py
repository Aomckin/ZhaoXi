"""Content-addressed raster storage shared by Experience, Perception and Session."""
import base64
import hashlib
import json
import os
import re
import sqlite3
from zhaoxi.reliability.sqlite import connect
import tempfile
from datetime import UTC, datetime
from pathlib import Path


class MediaBlobStore:
    def __init__(self, root):
        self.root=Path(root)

    def put(self, data_url):
        header,encoded=data_url.split(',',1)
        mime=header[5:].split(';')[0]
        raw=base64.b64decode(encoded,validate=True)
        digest=hashlib.sha256(raw).hexdigest()
        directory=self.root/'sha256'/digest[:2]
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/digest
        if not path.exists():
            fd,temp=tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(fd,'wb') as f:
                    f.write(raw);f.flush();os.fsync(f.fileno())
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        return {"$media":"sha256:"+digest,"hash":digest,"mime":mime,"size":len(raw),"thumbnail_ref":None}

    def encode(self, value):
        if isinstance(value,str) and re.match(r"^data:image/[a-zA-Z0-9.+-]+;base64,",value):
            return self.put(value)
        if isinstance(value,list):return [self.encode(x) for x in value]
        if isinstance(value,dict):return {k:self.encode(v) for k,v in value.items()}
        return value

    def decode(self, value):
        if isinstance(value,dict) and '$media' in value:
            digest=value.get('hash','')
            if not re.fullmatch('[0-9a-f]{64}',digest) or value['$media']!='sha256:'+digest:
                raise ValueError('invalid media reference')
            raw=(self.root/'sha256'/digest[:2]/digest).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('media hash mismatch')
            return 'data:'+value['mime']+';base64,'+base64.b64encode(raw).decode('ascii')
        if isinstance(value,list):return [self.decode(x) for x in value]
        if isinstance(value,dict):return {k:self.decode(v) for k,v in value.items()}
        return value

    def dumps(self, value):
        return json.dumps(self.encode(value),ensure_ascii=False,separators=(',',':'))

    def loads(self, value):
        return self.decode(json.loads(value))

    def stats(self):
        blobs=[p for p in (self.root/'sha256').glob('*/*') if re.fullmatch('[0-9a-f]{64}',p.name)]
        return {'media_blobs':len(blobs),'media_bytes':sum(p.stat().st_size for p in blobs)}


def database_metrics(path):
    path=Path(path)
    if not path.exists():return {'exists':False}
    with connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        pages=db.execute('PRAGMA page_count').fetchone()[0]
        free=db.execute('PRAGMA freelist_count').fetchone()[0]
        size=db.execute('PRAGMA page_size').fetchone()[0]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        last=db.execute("SELECT value FROM db_maintenance WHERE key='last_vacuum'").fetchone() if 'db_maintenance' in tables else None
    return {'exists':True,'db_size':path.stat().st_size,'wal_size':Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0,
            'live_pages':pages-free,'freelist_pages':free,'page_size':size,'last_vacuum':last[0] if last else None}


def vacuum_database(path, incremental=False):
    with connect(path) as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.execute('PRAGMA incremental_vacuum' if incremental else 'VACUUM')
        db.execute('CREATE TABLE IF NOT EXISTS db_maintenance (key TEXT PRIMARY KEY,value TEXT)')
        db.execute("INSERT OR REPLACE INTO db_maintenance VALUES ('last_vacuum',?)",(datetime.now(UTC).isoformat(),))
    return database_metrics(path)


def migrate_inline_media(path, *, dry_run=True, output_dir=None, cancel=lambda:False, progress=lambda x:None, media_directory=None):
    """Offline transaction for old inline images; never run on startup."""
    from zhaoxi.memory.migration import snapshot
    path=Path(path);store=MediaBlobStore(media_directory or path.parent/'media')
    output=Path(output_dir) if output_dir else path.parent/'media-migrations'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')
    output.mkdir(parents=True,exist_ok=True)
    backup=str(snapshot(path,output/(path.name+'.bak'))) if not dry_run else None
    report={'dry_run':dry_run,'backup':backup,'changed_rows':0,'inline_images':0,'unique_blobs':0,'bytes_removed':0}
    hashes=set()
    with connect(path.resolve().as_uri()+'?mode=ro',uri=True) if dry_run else connect(path) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,key,column in [('events','event_id','payload'),('observations','id','payload'),('sessions','session_id','messages_json')]:
            if table not in tables:continue
            cursor=db.execute(f'SELECT {key},{column} FROM {table}')
            while rows:=cursor.fetchmany(50):
                for row_id,payload in rows:
                    if cancel():raise RuntimeError('media migration cancelled; transaction rolled back')
                    if 'data:image/' not in payload:continue
                    value=json.loads(payload)
                    def convert(v):
                        if isinstance(v,str) and re.match(r'^data:image/[a-zA-Z0-9.+-]+;base64,',v):
                            raw=base64.b64decode(v.split(',',1)[1],validate=True)
                            digest=hashlib.sha256(raw).hexdigest();hashes.add(digest)
                            report['inline_images']+=1;report['bytes_removed']+=len(v)
                            return {'$media':'sha256:'+digest,'hash':digest,'mime':v[5:].split(';')[0],'size':len(raw),'thumbnail_ref':None} if dry_run else store.put(v)
                        if isinstance(v,list):return [convert(x) for x in v]
                        if isinstance(v,dict):return {k:convert(x) for k,x in v.items()}
                        return v
                    encoded=json.dumps(convert(value),ensure_ascii=False,separators=(',',':'))
                    if encoded!=payload:
                        report['changed_rows']+=1
                        if not dry_run:db.execute(f'UPDATE {table} SET {column}=? WHERE {key}=?',(encoded,row_id))
                progress({'phase':'media','changed_rows':report['changed_rows']})
    report['unique_blobs']=len(hashes)
    report['dedup_ratio']=round(1-len(hashes)/report['inline_images'],4) if report['inline_images'] else 0
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
