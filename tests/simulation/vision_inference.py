"""Actual CPU YOLOX image/blank/augmentation accuracy and latency acceptance."""
import argparse,json,math,time
from pathlib import Path
import cv2
import numpy as np
from perception.vision.yolox import YoloXDetector
from perception.vision.projection import PlaneCalibration
from scripts.prepare_vision_fixture import prepare,WEIGHTS_SHA

def iou(a,b):
    area=lambda r:max(0,r[2]-r[0])*max(0,r[3]-r[1])
    intersect=(max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3]))
    common=area(intersect);return common/(area(a)+area(b)-common)

def run(directory):
    directory.mkdir(parents=True,exist_ok=False);assets=Path('artifacts/simulation/vision-assets').resolve();prepare(assets)
    report={'passed':False,'backend':'OpenCV DNN CPU','opencv':cv2.__version__,'fixture_scope':'recorded virtual calibration only','frames':[]}
    try:
        detector=YoloXDetector(assets/'yolox.onnx',WEIGHTS_SHA);calibration=PlaneCalibration.load(assets/'calibration.toml');source=cv2.imread(str(assets/'bus.jpg'))
        rng=np.random.default_rng(1)
        positives=[source,cv2.convertScaleAbs(source,alpha=.75),cv2.convertScaleAbs(source,alpha=1.15),cv2.GaussianBlur(source,(5,5),0),np.clip(source.astype(np.int16)+rng.integers(-10,11,source.shape),0,255).astype(np.uint8)]
        frames=positives+[np.zeros_like(source),np.full_like(source,114)]
        tp=fp=fn=0
        for index,image in enumerate(frames):
            start=time.monotonic_ns();detections=detector.detect(image);latency=time.monotonic_ns()-start
            buses=[d for d in detections if d.class_id==5];positive=index<len(positives)
            entry={'index':index,'positive':positive,'latency_ns':latency,'buses':[{'confidence':d.confidence,'bbox':d.xyxy} for d in buses]}
            if positive:
                valid=[d for d in buses if iou(d.xyxy,(10,230,800,725))>=.8]
                if valid:
                    tp+=1;point=calibration.project(valid[0],(810,1080));error=math.hypot(point.x-2,point.y-.290416666666667)
                    entry.update(iou=iou(valid[0].xyxy,(10,230,800,725)),projection_error_m=error)
                    if error>.1:raise RuntimeError('virtual projection error exceeds 0.1 m')
                else:fn+=1
                fp+=max(0,len(buses)-1)
            else:fp+=len(buses)
            report['frames'].append(entry)
            if latency>1_000_000_000:raise RuntimeError('inference capture latency exceeds 1 s')
        report.update(precision=tp/max(1,tp+fp),recall=tp/max(1,tp+fn),false_positive=fp)
        if tp!=len(positives) or fp:raise RuntimeError('fixture detection precision/recall failure')
        report['passed']=True
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}'
    (directory/'summary.json').write_text(json.dumps(report,indent=2));return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();r=run(a.run_dir);print(json.dumps(r));raise SystemExit(0 if r['passed'] else 1)
