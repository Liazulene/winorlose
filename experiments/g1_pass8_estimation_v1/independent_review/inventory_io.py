"""Lossless segmented-gzip inventory storage; all hashes checked on read."""
import gzip,hashlib,json,pathlib
LIMIT=192*1024
def sha(data):return hashlib.sha256(data).hexdigest()
def pack(raw,path,external=None):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True);packed=gzip.compress(raw,mtime=0)
    if external is not None:
        external=pathlib.Path(external);external.mkdir(parents=True,exist_ok=True);(external/(path.name+'.gz')).write_bytes(packed)
    parts=[]
    for i,start in enumerate(range(0,len(packed),LIMIT),1):
        content=packed[start:start+LIMIT];dest=path.with_name(path.name+f'.gz.part{i:02d}');dest.write_bytes(content)
        parts.append({'name':dest.name,'bytes':len(content),'sha256':sha(content)})
    manifest={'encoding':'gzip of exact UTF-8 JSON bytes, segmented in named order','raw_filename':path.name,'raw_bytes':len(raw),'raw_sha256':sha(raw),'gzip_bytes':len(packed),'gzip_sha256':sha(packed),'parts':parts}
    target=path.with_name(path.name+'.segments.json');target.write_text(json.dumps(manifest,indent=2)+'\n')
    assert read_raw(target)==raw
    return manifest

def read_raw(path):
    path=pathlib.Path(path)
    if path.suffix=='.json' and not path.name.endswith('.segments.json') and path.exists():return path.read_bytes()
    if path.name.endswith('.gz') and path.exists():return gzip.decompress(path.read_bytes())
    if not path.name.endswith('.segments.json'):path=path.with_name(path.name.removesuffix('.gz')+'.segments.json')
    manifest=json.loads(path.read_text());contents=[]
    for part in manifest['parts']:
        data=(path.parent/part['name']).read_bytes()
        if len(data)!=part['bytes'] or sha(data)!=part['sha256']:raise ValueError('inventory segment hash/size mismatch:'+part['name'])
        contents.append(data)
    packed=b''.join(contents)
    if len(packed)!=manifest['gzip_bytes'] or sha(packed)!=manifest['gzip_sha256']:raise ValueError('reassembled gzip hash/size mismatch')
    raw=gzip.decompress(packed)
    if len(raw)!=manifest['raw_bytes'] or sha(raw)!=manifest['raw_sha256']:raise ValueError('uncompressed JSON hash/size mismatch')
    return raw

def load(path):return json.loads(read_raw(path))
