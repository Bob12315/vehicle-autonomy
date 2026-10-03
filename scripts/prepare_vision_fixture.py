#!/usr/bin/env python3
"""Fetch checksum-pinned public assets and create an explicit virtual recording."""
import argparse,hashlib,json
from pathlib import Path
import urllib.request

WEIGHTS_SHA='c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'
IMAGE_SHA='c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63'
ASSETS={'yolox.onnx':('https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_yolox/object_detection_yolox_2022nov.onnx',WEIGHTS_SHA),'bus.jpg':('https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg',IMAGE_SHA)}

def prepare(directory):
    directory.mkdir(parents=True,exist_ok=True)
    for name,(url,digest) in ASSETS.items():
        path=directory/name
        if not path.exists():
            with urllib.request.urlopen(url,timeout=90) as response:path.write_bytes(response.read(50*1024*1024))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError(f'asset checksum mismatch: {name}')
    (directory/'calibration.toml').write_text('''schema = 1
frame = "odom"
width = 810
height = 1080
fx = 600.0
fy = 600.0
cx = 405.0
cy = 540.0
translation = [2.0, 1.2, 3.0]
rotation = [1.0, 0.0, 0.0, 0.0]
plane_z = 0.05
max_distance_m = 4.0
source = "synthetic downward camera on a textured plane; photograph is a virtual texture, not a calibrated real street; manual bus contact pixel (405,725); no field camera evidence"
''')
    recording={'schema':1,'kind':'recorded_virtual_camera','source':'finite synthetic 2 Hz static plane-camera recording using a real public bus photograph; COCO bus→bucket_1 is a fixture mapping only',
        'model':'yolox.onnx','model_sha256':WEIGHTS_SHA,'calibration':'calibration.toml','class_map':{'5':'bucket_1'},'threshold':.5,
        'frames':[{'pts_ns':i*500_000_000,'path':'bus.jpg','sha256':IMAGE_SHA} for i in range(500)]}
    (directory/'recording.json').write_text(json.dumps(recording,indent=2))
    provenance={'assets':ASSETS,'model_docs':'https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox','model_license':'Apache-2.0','image_source':'https://github.com/ultralytics/assets','annotation':{'class_id':5,'bbox':[10,230,800,725],'contact_pixel':[405,725],'virtual_world_contact':[2,.290416666666667,.05]},'scope':'software virtual recording only; no real image-to-world calibration or CUADC bucket recognition'}
    (directory/'provenance.json').write_text(json.dumps(provenance,indent=2));return directory/'recording.json'

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,default=Path('artifacts/simulation/vision-assets'));args=parser.parse_args();print(prepare(args.directory).resolve())
