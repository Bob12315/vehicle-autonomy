"""Pixel-only H marker for the supplied yellow-disc/black-H simulation asset.

The training set's white-on-black H is a different visual domain. This bounded
shape detector is reported separately from PT predictions; no map position or
Gazebo model identity is used to manufacture a label.
"""
from .yolox import PixelDetection


def detect_h(bgr):
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(bgr,cv2.COLOR_BGR2HSV)
    yellow=cv2.inRange(hsv,np.array((15,80,70),np.uint8),np.array((45,255,255),np.uint8))
    points=cv2.findNonZero(yellow)
    if points is None or len(points)<150:return ()
    hull=cv2.convexHull(points);region=np.zeros(yellow.shape,np.uint8);cv2.fillConvexPoly(region,hull,255)
    dark=((hsv[:,:,2]<85)&(region>0)).astype(np.uint8)
    count,labels,stats,_=cv2.connectedComponentsWithStats(dark,8)
    result=[]
    for i in range(1,count):
        x,y,w,h,area=map(int,stats[i])
        if w<12 or h<12 or area<40 or not .5<=w/h<=1.6:continue
        shape=cv2.resize((labels[y:y+h,x:x+w]==i).astype(np.float32),(60,60),interpolation=cv2.INTER_AREA)
        best=0.
        for candidate in (shape,np.rot90(shape)):
            left=float(candidate[:,2:11].mean());right=float(candidate[:,49:58].mean())
            top_gap=float(candidate[:18,22:38].mean());bottom_gap=float(candidate[42:,22:38].mean())
            cross=float(candidate[19:42,:].mean(axis=1).max())
            if min(left,right)<.65 or max(top_gap,bottom_gap)>.18 or cross<.8:continue
            best=max(best,min(1.,.4*left+.4*right+.2*cross))
        if best>=.75:result.append(PixelDetection(1,best,(float(x),float(y),float(x+w),float(y+h))))
    # A unique marker is necessary; multiple plausible yellow Hs are ambiguous.
    return tuple(result) if len(result)==1 else ()


def overlap(a,b):
    x0=max(a[0],b[0]);y0=max(a[1],b[1]);x1=min(a[2],b[2]);y1=min(a[3],b[3])
    area=max(0,x1-x0)*max(0,y1-y0)
    return area/max(1e-9,min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])))
