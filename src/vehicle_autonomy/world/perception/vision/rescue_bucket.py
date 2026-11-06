"""Pixel-only surface check for the locked rescue scene's neutral grey buckets.

This is a postcondition on a PT bucket candidate, not a detector, scene query or
general real-world bucket classifier. It rejects dark lettering on saturated
ground that becomes a second bucket candidate at the revised off-centre view.
"""
import math


def has_bucket_surface(image,detection):
    import cv2,numpy as np
    height,width=image.shape[:2]
    x0,y0,x1,y1=detection.xyxy
    left=max(0,math.floor(x0));right=min(width,math.ceil(x1))
    top=max(0,math.floor(y0));bottom=min(height,math.ceil(y1))
    if right-left<3 or bottom-top<3:return False
    hsv=cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2HSV)
    # JPEG and the oblique rim can tint a small open bucket. Keep that rim;
    # the saturated ground lettering patch still has no qualifying surface.
    neutral_bright=(hsv[:,:,1]<=95)&(hsv[:,:,2]>=90)
    return float(np.count_nonzero(neutral_bright))/neutral_bright.size>=.12
