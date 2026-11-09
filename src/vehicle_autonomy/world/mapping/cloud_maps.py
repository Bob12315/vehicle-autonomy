"""Bounded estimated-cloud accumulation and immutable PCD map resources.

No scan registration, pose estimation, vehicle port, ROS dependency or truth
input lives here. Points must already be registered by the admitted algorithm.
"""
from datetime import datetime,timezone
import hashlib,json,os,re,shutil,stat
from pathlib import Path
from uuid import uuid4


MAX_POINTS=500000
MAX_BYTES=8*1024*1024
ID=re.compile(r'map3d-[0-9a-f]{64}')


def pcd_bytes(points):
    import numpy as np
    values=np.asarray(points,dtype='<f4')
    if values.ndim!=2 or values.shape[1]!=4 or not 0<len(values)<=MAX_POINTS:raise ValueError('bounded XYZ/intensity map required')
    if not np.isfinite(values).all() or np.abs(values[:,:3]).max()>1000:raise ValueError('invalid map coordinates')
    header=('VERSION .7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n'
        f'WIDTH {len(values)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(values)}\nDATA binary\n')
    return header.encode()+values.tobytes()


def read_pcd(data):
    import numpy as np
    if type(data) is not bytes or not 0<len(data)<=MAX_BYTES:raise ValueError('PCD byte budget')
    try:raw,payload=data.split(b'DATA binary\n',1)
    except ValueError:raise ValueError('only audited binary PCD is supported') from None
    if len(raw)>2048:raise ValueError('PCD header budget')
    fields={}
    for line in raw.decode('ascii').splitlines():
        key,_,value=line.partition(' ')
        if key in fields:raise ValueError('duplicate PCD header')
        fields[key]=value
    expected={'VERSION':'.7','FIELDS':'x y z intensity','SIZE':'4 4 4 4','TYPE':'F F F F','COUNT':'1 1 1 1','HEIGHT':'1','VIEWPOINT':'0 0 0 1 0 0 0'}
    if set(fields)!=set(expected)|{'WIDTH','POINTS'} or any(fields.get(k)!=v for k,v in expected.items()):raise ValueError('PCD layout/version mismatch')
    count=int(fields['POINTS'])
    if not 0<count<=MAX_POINTS or fields['WIDTH']!=str(count) or len(payload)!=count*16:raise ValueError('PCD dimensions/length mismatch')
    values=np.frombuffer(payload,dtype='<f4').reshape(count,4)
    if not np.isfinite(values).all() or np.abs(values[:,:3]).max()>1000:raise ValueError('invalid map coordinates')
    return values


class VoxelMap:
    def __init__(self,*,resolution=.15,max_points=MAX_POINTS,radius=80.,min_observations=3):
        if not .05<=resolution<=1. or not 1000<=max_points<=MAX_POINTS or not 5<=radius<=100.:raise ValueError('map resource limits')
        self.resolution,self.max_points,self.radius=resolution,max_points,radius
        if type(min_observations) is not int or not 1<=min_observations<=20:raise ValueError('bounded map observation filter required')
        self.min_observations=min_observations
        self.cells={};self.revision=0;self.paused=False;self.error=None;self.accepted=0;self.filtered=0

    def update(self,points):
        import numpy as np
        if self.paused or self.error:return
        values=np.asarray(points,dtype=np.float32)
        if values.ndim!=2 or values.shape[1]!=4 or len(values)>200000:raise ValueError('registered cloud layout/budget')
        mask=np.isfinite(values).all(axis=1)&(np.linalg.norm(values[:,:3],axis=1)<=self.radius)
        self.filtered+=int((~mask).sum());values=values[mask]
        if not len(values):return
        keys,indices,counts=np.unique(np.floor(values[:,:3]/self.resolution).astype('int64'),axis=0,return_inverse=True,return_counts=True)
        new=[tuple(int(v) for v in key) for key in keys]
        if len(self.cells)+sum(k not in self.cells for k in new)>self.max_points:
            self.error='map point capacity exhausted; updates stopped';return
        sums=np.stack([np.bincount(indices,weights=values[:,i],minlength=len(keys)) for i in range(4)],axis=1)
        for key,total,count in zip(new,sums,counts):
            centroid=total/count
            # Average each scan's voxel centroid with bounded history weight.
            # Raw return density must not make the first scan dominate forever.
            count=1
            if key in self.cells:
                old,n=self.cells[key];centroid=(old*n+centroid)/(n+1);count=min(n+1,100)
            self.cells[key]=(centroid,int(count))
        self.accepted+=len(values);self.revision+=1

    def points(self):
        import numpy as np
        return np.asarray([self.cells[k][0] for k in sorted(self.cells) if self.cells[k][1]>=self.min_observations],dtype=np.float32).reshape(-1,4)


def load_limits(root):
    """Versioned operator configuration; no unbounded worker allocations."""
    limits=json.loads((Path(root)/'configs/mid360-map.json').read_text())
    if type(limits) is not dict or set(limits)!={'resolution','max_points','radius','min_observations'}:
        raise ValueError('explicit map resolution, capacity, range and observation filter required')
    if any(type(limits[k]) not in (int,float) for k in ('resolution','radius')) or any(type(limits[k]) is not int for k in ('max_points','min_observations')):
        raise ValueError('numeric map dimensions and integer resource budgets required')
    VoxelMap(**limits)
    return limits


class MapCatalog:
    def __init__(self,directory):
        self.root=Path(directory).absolute();self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.resolve()!=self.root:raise ValueError('real map catalog required')
        info=self.root.stat();self.identity=(info.st_dev,info.st_ino)

    def _check(self):
        info=self.root.stat()
        if self.root.resolve()!=self.root or (info.st_dev,info.st_ino)!=self.identity:raise ValueError('map catalog changed')

    def save(self,name,data,metadata):
        self._check();read_pcd(data)
        if len(list(self.root.glob('map3d-*')))>=100:raise ValueError('persistent map count budget exhausted')
        if set(metadata)&{'id','schema','version','sha256','saved_at','name','points'}:raise ValueError('reserved map metadata fields')
        if type(name) is not str or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):raise ValueError('bounded map name required')
        for key in ('vehicle','sensor','world','algorithm','frame_id','frame_epoch','source_capture_ros_ns','created_at'):
            if key not in metadata:raise ValueError('missing map provenance: '+key)
        if metadata['vehicle'] not in ('rover','copter'):raise ValueError('simulation vehicle map required')
        for key in ('frame_id','frame_epoch'):
            if type(metadata[key]) is not str or not re.fullmatch(r'[A-Za-z0-9_/-]{1,160}',metadata[key]):raise ValueError('invalid coordinate provenance')
        if type(metadata['source_capture_ros_ns']) is not int or metadata['source_capture_ros_ns']<=0:raise ValueError('map acquisition time required')
        if datetime.fromisoformat(metadata['created_at']).tzinfo is None:raise ValueError('map creation timestamp missing zone')
        document=dict(metadata,schema=1,version=1,name=name.strip(),points=len(read_pcd(data)),
            sha256=hashlib.sha256(data).hexdigest(),saved_at=datetime.now(timezone.utc).isoformat())
        canonical=json.dumps(document,allow_nan=False,ensure_ascii=False,sort_keys=True).encode()
        identity='map3d-'+hashlib.sha256(canonical).hexdigest();document['id']=identity
        raw=json.dumps(document,allow_nan=False,ensure_ascii=False,sort_keys=True).encode()
        if len(raw)>65536:raise ValueError('map metadata budget')
        folder=self.root/('.tmp-'+uuid4().hex);folder.mkdir(mode=0o700)
        try:
            for filename,payload in (('map.pcd',data),('metadata.json',raw)):
                fd=os.open(folder/filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
            folder.rename(self.root/identity)
        except BaseException:shutil.rmtree(folder);raise
        return document

    def load(self,identity):
        self._check()
        if type(identity) is not str or not ID.fullmatch(identity):raise ValueError('registered map id required')
        folder=self.root/identity
        if folder.resolve()!=folder:raise ValueError('symlinked map rejected')
        def read(name,limit):
            fd=os.open(folder/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_size>limit:raise ValueError('map file ownership/size')
                with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
            finally:os.close(fd)
            if len(data)>limit:raise ValueError('map file grew')
            return data
        document=json.loads(read('metadata.json',65536));data=read('map.pcd',MAX_BYTES)
        if not isinstance(document,dict):raise ValueError('map metadata document required')
        if document.get('schema')!=1 or document.get('version')!=1 or document.get('id')!=identity:raise ValueError('map identity/version')
        canonical=json.dumps({k:v for k,v in document.items() if k!='id'},allow_nan=False,ensure_ascii=False,sort_keys=True).encode()
        if identity!='map3d-'+hashlib.sha256(canonical).hexdigest():raise ValueError('map metadata checksum mismatch')
        if hashlib.sha256(data).hexdigest()!=document['sha256']:raise ValueError('map checksum mismatch')
        if document['points']!=len(read_pcd(data)):raise ValueError('map count mismatch')
        if any(type(document[k]) is not str or not re.fullmatch(r'[A-Za-z0-9_/-]{1,160}',document[k]) for k in ('frame_id','frame_epoch')):
            raise ValueError('map coordinate provenance')
        for key in ('created_at','saved_at'):
            if datetime.fromisoformat(document[key]).tzinfo is None:raise ValueError('map timestamp missing zone')
        return document,data

    def list(self):
        result=[]
        for folder in sorted(self.root.glob('map3d-*')):
            try:document,_=self.load(folder.name);result.append(document)
            except (OSError,ValueError,KeyError,TypeError):continue
        return result
