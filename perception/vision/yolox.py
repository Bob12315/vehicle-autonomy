"""CPU OpenCV DNN YOLOX adapter. Decode follows the published YOLOX grid format.
Model/input convention: https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox
"""
from dataclasses import dataclass
import math
import hashlib

@dataclass(frozen=True,slots=True)
class PixelDetection:
    class_id:int
    confidence:float
    xyxy:tuple[float,float,float,float]
    def __post_init__(self):
        if type(self.class_id) is not int or self.class_id<0 or not math.isfinite(self.confidence) or not 0<=self.confidence<=1:raise ValueError('invalid pixel detection')
        if len(self.xyxy)!=4 or not all(math.isfinite(x) for x in self.xyxy) or self.xyxy[2]<=self.xyxy[0] or self.xyxy[3]<=self.xyxy[1]:raise ValueError('invalid pixel box')

class YoloXDetector:
    def __init__(self,path,expected_sha256,threshold=.5):
        import cv2
        import numpy as np
        if not path.is_file():raise ValueError('regular ONNX file required; no device input')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha256:raise ValueError('detector weights hash mismatch')
        if isinstance(threshold,bool) or not .1<=threshold<=1:raise ValueError('invalid detector threshold')
        cv2.setNumThreads(1)
        self.net=cv2.dnn.readNetFromONNX(str(path));self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV);self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.threshold=threshold
        grids=[];strides=[]
        for stride in (8,16,32):
            n=640//stride
            grids.extend((x,y) for y in range(n) for x in range(n));strides.extend([stride]*(n*n))
        self.grids=np.array(grids,dtype=np.float32);self.strides=np.array(strides,dtype=np.float32)[:,None]

    def detect(self,bgr):
        import cv2
        import numpy as np
        if bgr is None or len(bgr.shape)!=3 or bgr.shape[2]!=3:raise ValueError('BGR image required')
        height,width=bgr.shape[:2];ratio=min(640/width,640/height)
        canvas=np.full((640,640,3),114,dtype=np.float32)
        image=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB);resized=cv2.resize(image,(int(width*ratio),int(height*ratio)))
        canvas[:resized.shape[0],:resized.shape[1]]=resized
        self.net.setInput(canvas.transpose(2,0,1)[None])
        raw=self.net.forward()[0]
        if raw.shape!=(8400,85) or not np.isfinite(raw).all():raise ValueError('unexpected YOLOX output')
        centers=(raw[:,:2]+self.grids)*self.strides;size=np.exp(raw[:,2:4])*self.strides
        scores=raw[:,4,None]*raw[:,5:];classes=scores.argmax(axis=1);confidence=scores.max(axis=1)
        xywh=np.concatenate((centers-size/2,size),axis=1)/ratio
        keep=cv2.dnn.NMSBoxesBatched(xywh.tolist(),confidence.tolist(),classes.tolist(),self.threshold,.5)
        result=[]
        for index in keep:
            x,y,w,h=map(float,xywh[index]);x0=max(0,x);y0=max(0,y);x1=min(width,x+w);y1=min(height,y+h)
            if x1>x0 and y1>y0:result.append(PixelDetection(int(classes[index]),float(confidence[index]),(x0,y0,x1,y1)))
        return tuple(result)
