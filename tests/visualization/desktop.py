"""Native X11 test input, pinned to the actual owned RViz PID.

Only selects an inert RViz pending goal. It never confirms a vehicle Action.
"""
import ctypes as C
import ctypes.util
import os,time


def goal(pid,*,capture=None,select=True):
    x=C.CDLL(ctypes.util.find_library('X11'));t=C.CDLL(ctypes.util.find_library('Xtst'));D=C.c_void_p;W=C.c_ulong
    x.XOpenDisplay.argtypes=[C.c_char_p];x.XOpenDisplay.restype=D;display=x.XOpenDisplay(os.environ.get('DISPLAY',':1').encode())
    if not display:raise RuntimeError('native X11 desktop unavailable')
    x.XDefaultRootWindow.argtypes=[D];x.XDefaultRootWindow.restype=W;root=x.XDefaultRootWindow(display)
    x.XInternAtom.argtypes=[D,C.c_char_p,C.c_int];x.XInternAtom.restype=W;atom=x.XInternAtom(display,b'_NET_WM_PID',False)
    x.XQueryTree.argtypes=[D,W,C.POINTER(W),C.POINTER(W),C.POINTER(C.POINTER(W)),C.POINTER(C.c_uint)]
    x.XGetWindowProperty.argtypes=[D,W,W,C.c_long,C.c_long,C.c_int,W,C.POINTER(W),C.POINTER(C.c_int),C.POINTER(C.c_ulong),C.POINTER(C.c_ulong),C.POINTER(C.POINTER(C.c_ubyte))]
    x.XGetGeometry.argtypes=[D,W,C.POINTER(W),C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_uint),C.POINTER(C.c_uint),C.POINTER(C.c_uint),C.POINTER(C.c_uint)]
    x.XTranslateCoordinates.argtypes=[D,W,W,C.c_int,C.c_int,C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(W)]
    x.XFree.argtypes=[D];x.XRaiseWindow.argtypes=[D,W];x.XSetInputFocus.argtypes=[D,W,C.c_int,W];x.XSync.argtypes=[D,C.c_int];x.XCloseDisplay.argtypes=[D]
    candidates=[]
    def visit(window,depth=0):
        if depth>5:return
        actual=W();fmt=C.c_int();items=C.c_ulong();after=C.c_ulong();data=C.POINTER(C.c_ubyte)()
        x.XGetWindowProperty(display,window,atom,0,1,False,0,C.byref(actual),C.byref(fmt),C.byref(items),C.byref(after),C.byref(data))
        matched=bool(items.value and fmt.value==32 and C.cast(data,C.POINTER(C.c_ulong))[0]==pid)
        if data:x.XFree(data)
        if matched:
            rr=W();xx=C.c_int();yy=C.c_int();width=C.c_uint();height=C.c_uint();border=C.c_uint();bits=C.c_uint()
            if x.XGetGeometry(display,window,C.byref(rr),C.byref(xx),C.byref(yy),C.byref(width),C.byref(height),C.byref(border),C.byref(bits)) and width.value>600 and height.value>400:candidates.append((width.value*height.value,window,width.value,height.value))
        rr=W();parent=W();children=C.POINTER(W)();count=C.c_uint()
        if x.XQueryTree(display,window,C.byref(rr),C.byref(parent),C.byref(children),C.byref(count)):
            for i in range(count.value):visit(children[i],depth+1)
            if children:x.XFree(children)
    try:
        visit(root)
        if not candidates:raise RuntimeError('no visible RViz client window matching owned PID')
        _,window,width,height=max(candidates);xx=C.c_int();yy=C.c_int();child=W()
        x.XTranslateCoordinates(display,window,root,0,0,C.byref(xx),C.byref(yy),C.byref(child))
        # Ask the WM to activate our own client. Raising a window alone is not
        # sufficient when another application is full-screen. Never type into
        # an unverified focus owner.
        class Message(C.Structure):
            _fields_=[('type',C.c_int),('serial',C.c_ulong),('send_event',C.c_int),('display',D),('window',W),('message_type',W),('format',C.c_int),('data',C.c_long*5)]
        class Event(C.Union):_fields_=[('message',Message),('pad',C.c_long*24)]
        event=Event();event.message.type=33;event.message.display=display;event.message.window=window;event.message.message_type=x.XInternAtom(display,b'_NET_ACTIVE_WINDOW',False);event.message.format=32;event.message.data[0]=2
        x.XSendEvent.argtypes=[D,W,C.c_int,C.c_long,C.POINTER(Event)];x.XSendEvent(display,root,False,(1<<20)|(1<<19),C.byref(event));x.XRaiseWindow(display,window);x.XSync(display,False);time.sleep(.35)
        x.XSetInputFocus(display,window,1,0);x.XSync(display,False);time.sleep(.15)
        x.XGetInputFocus.argtypes=[D,C.POINTER(W),C.POINTER(C.c_int)];focused=W();revert=C.c_int();x.XGetInputFocus(display,C.byref(focused),C.byref(revert))
        cursor=focused.value
        while cursor and cursor not in (window,root):
            rr=W();parent=W();children=C.POINTER(W)();count=C.c_uint()
            if not x.XQueryTree(display,cursor,C.byref(rr),C.byref(parent),C.byref(children),C.byref(count)):break
            if children:x.XFree(children)
            cursor=parent.value
        if cursor!=window:raise RuntimeError('RViz does not own keyboard focus; no native test input sent')
        if capture:
            # Capture the visible owned-client rectangle from the composited
            # desktop. Reading the client's redirected backing pixmap can mix
            # stale Qt widgets with a current OpenGL child surface.
            class XImage(C.Structure):_fields_=[('width',C.c_int),('height',C.c_int),('xoffset',C.c_int),('format',C.c_int),('data',D),('byte_order',C.c_int),('bitmap_unit',C.c_int),('bitmap_bit_order',C.c_int),('bitmap_pad',C.c_int),('depth',C.c_int),('bytes_per_line',C.c_int),('bits_per_pixel',C.c_int),('red_mask',C.c_ulong),('green_mask',C.c_ulong),('blue_mask',C.c_ulong)]
            x.XGetImage.argtypes=[D,W,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_ulong,C.c_int];x.XGetImage.restype=C.POINTER(XImage);x.XDestroyImage.argtypes=[C.POINTER(XImage)]
            pointer=x.XGetImage(display,root,xx.value,yy.value,width,height,C.c_ulong(-1).value,2)
            if not pointer:raise RuntimeError('owned RViz window capture unavailable')
            try:
                value=pointer.contents
                if value.bits_per_pixel!=32 or value.byte_order!=0 or value.red_mask!=0xff0000:raise RuntimeError('unsupported native capture pixel layout')
                from PIL import Image
                Image.frombytes('RGB',(width,height),C.string_at(value.data,value.bytes_per_line*height),'raw','BGRX',value.bytes_per_line,1).save(capture)
            finally:x.XDestroyImage(pointer)
        x.XStringToKeysym.argtypes=[C.c_char_p];x.XStringToKeysym.restype=W;x.XKeysymToKeycode.argtypes=[D,W];x.XKeysymToKeycode.restype=C.c_uint
        t.XTestFakeKeyEvent.argtypes=[D,C.c_uint,C.c_int,C.c_ulong];t.XTestFakeButtonEvent.argtypes=[D,C.c_uint,C.c_int,C.c_ulong];t.XTestFakeMotionEvent.argtypes=[D,C.c_int,C.c_int,C.c_int,C.c_ulong]
        # Rover's native top-down profile is fixed to odom at 80 px/m.
        # Select a straight-ahead 1.5 m goal, then drag its preview yaw east.
        px=int(xx.value+480+(width-480)*.5+120);py=int(yy.value+70+(height-110)*.5)
        if not select:return dict(owned_rviz_pid=pid,window=int(window),client_size=[width,height],focus_verified=True,window_only_capture=bool(capture))
        # Confirm the pointer belongs to our client before any native click.
        t.XTestFakeMotionEvent(display,-1,px-120,py,0);x.XSync(display,False)
        top=window
        while True:
            rr=W();parent=W();children=C.POINTER(W)();count=C.c_uint();x.XQueryTree(display,top,C.byref(rr),C.byref(parent),C.byref(children),C.byref(count))
            if children:x.XFree(children)
            if parent.value==root:break
            if not parent.value:raise RuntimeError('RViz window detached during native input')
            top=parent.value
        rx=C.c_int();ry=C.c_int();wx=C.c_int();wy=C.c_int();mask=C.c_uint();rr=W();under=W()
        x.XQueryPointer.argtypes=[D,W,C.POINTER(W),C.POINTER(W),C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_int),C.POINTER(C.c_uint)]
        x.XQueryPointer(display,root,C.byref(rr),C.byref(under),C.byref(rx),C.byref(ry),C.byref(wx),C.byref(wy),C.byref(mask))
        if under.value!=top:raise RuntimeError('RViz render window occluded; no native click sent')
        # Click the actual native 2D Goal Pose toolbar button, visible at this
        # location in the fixed acceptance profile. No focus-sensitive key.
        t.XTestFakeMotionEvent(display,-1,xx.value+375,yy.value+43,0);t.XTestFakeButtonEvent(display,1,True,0);t.XTestFakeButtonEvent(display,1,False,0);x.XSync(display,False);time.sleep(.2)
        t.XTestFakeMotionEvent(display,-1,px,py,0);t.XTestFakeButtonEvent(display,1,True,0);x.XSync(display,False);time.sleep(.2)
        t.XTestFakeMotionEvent(display,-1,px+30,py,0);x.XSync(display,False);time.sleep(.15);t.XTestFakeButtonEvent(display,1,False,0);x.XSync(display,False)
        return dict(actual_native_mouse=True,owned_rviz_pid=pid,window=int(window),client_size=[width,height])
    finally:x.XCloseDisplay(display)
