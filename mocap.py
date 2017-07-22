#! /usr/bin/env python3

import numpy as np
import cv2
import time
import argparse
import logging
import sys
import copy
import imutils
import datetime
import threading
import ftpConn
import queue
from collections import deque

MOTION_FRAME_WIDTH = 300
FPS=30.0

FORMAT = '%(asctime)-15s %(threadName)-8s %(levelname)-8s %(message)s'
logging.basicConfig(format=FORMAT,
                    #level=logging.INFO,
                    level=logging.DEBUG,
                    )

log = logging.getLogger(__name__)

def parseArgs():
    ap = argparse.ArgumentParser()
    ap.add_argument("-r", "--resolution", \
            help="resolution of result vids WxH",
            default='960x720')
    ap.add_argument("-a", "--min-area-percent", type=float, \
            default=0.2, help="min area size in percentage",
            dest='minAreaPercent')
    ap.add_argument("-p", "--pre-frames", type=int, \
            default=80, dest='preframes',
            help="prior non motion frames to keep")


    args = vars(ap.parse_args())
    try:
        reso = args['resolution'].split('x')
    except Exception as e:
        reso = '960x720'
    try:
        args['w'] = int(reso[0])
    except Exception as e:
        args['w'] = 960
    try:
        args['h'] = int(reso[1])
    except Exception as e:
        args['h'] = 720

    scalar = float(MOTION_FRAME_WIDTH) / args['w'];
    log.debug("w,h %d,%d" % (args['w'],args['h']))
    bigarea = args['w'] * args['h']
    smallarea = float(bigarea) * scalar * scalar
    args['areaThresh'] = float(args['minAreaPercent'])/100 * \
                        smallarea
    log.debug("bigarea: %d" % (bigarea))
    log.debug("scalar: %.3f" % (scalar))
    log.debug("smallarea: %d" % (smallarea))
    log.debug("areaThresh: %d" % (args['areaThresh']))
    
    return args

def setWidthHeight(cap,w,h):
    wprop=cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    hprop=cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

def getWidthHeight(cap):
    w=cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h=cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    log.debug("cap w,h %d,%d" % (w,h))
    return w,h

def setupCaptureDevice(args):

    for i in range(-1,40):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            log.info("device %d opened" % (i))
            setWidthHeight(cap, args['w'], args['h'])
            w,h = getWidthHeight(cap)
            args['h'] = h
            args['w'] = w
            time.sleep(5)
            return cap
        else:
            log.info("device %d not opened" % i)

    return None

def genMotionFrame(rawFrame):
    motionFrame = imutils.resize(rawFrame, width=MOTION_FRAME_WIDTH)
    motionFrame = cv2.cvtColor(motionFrame, 
            cv2.COLOR_BGR2GRAY)
    motionFrame = cv2.GaussianBlur(motionFrame, 
            (21,21), 0)
    return motionFrame

def detectMotion(motionFrameFirst,
        motionFrame,
        areaThresh):

    motionFrame = cv2.absdiff(motionFrameFirst,
            motionFrame) # simple diff

    motionFrame = cv2.threshold(motionFrame, 25, 255,
            cv2.THRESH_BINARY)[1] # make B/W

    numberMotionBlocks = cv2.countNonZero(motionFrame)
    if numberMotionBlocks > areaThresh:
        log.info("OK %d > %d" % (
            numberMotionBlocks,
            areaThresh,
            ))
        return True
    else:
        return False

def getTimeStamp():
    return datetime.datetime.now().strftime( \
        "%Y.%m.%d.%H.%M.%S"),

def addText(f):
    now = getTimeStamp()
    try:
        cv2.putText(f, str(now), (10,f.shape[0]-10), \
            cv2.FONT_HERSHEY_PLAIN, 1.0, \
            (255,255,255), 1)
    except Exception as e:
        log.error("addtext error: %s" % (e))
    return f

def keepCapturing(firstFrame, cap):
    M = deque([firstFrame], maxlen=5)
    S = deque(maxlen=120) # holds bool
    L = list()
    while True:
        (retval, rawFrame) = cap.read()
        if not retval:
            log.warning("cap.read() error: %s" % (e))
            time.sleep(1)
            continue

        motionFrame = genMotionFrame(rawFrame)

        S.append(detectMotion(M[0], motionFrame, 0))
        
        if sum(S) > 0: # if deque sum is greater than 0, keep recording
            L.append(addText(rawFrame))
            M.append(motionFrame)
        else:  # if no motion in 120 frames, break
            break

        if len(L) > 300:
            log.warning("Buffer over 300!")
            break

    return L

def initFtp():
    c = ftpConn.Creds()
    wd = "htdocs/python_test/"
    return ftpConn.ftpConn(c.host,c.user,c.passwd,wd)

def cleanupFtp():
    ftp = initFtp()
    ftpConn.rmOldFiles(ftp,limitSeconds=60*60*24*2)
    ftp.quit()

def sendToFtp(outfile):
    ftp = initFtp()
    ftp.uploadFile(outfile)
    log.info("sent to ftp %s" % outfile)
    ftp.quit()

def ftpOut(ftpQ):
    while True:
        outfile = ftpQ.get()
        try:
            sendToFtp(outfile)
        except Exception as e:
            log.error("sendToFtp error: %s" % e)
        finally:
            log.debug("sendToFtp() done")

def writeOut(writeQ, ftpQ):
    while True:
        D = writeQ.get()
        fourcc = cv2.VideoWriter_fourcc(*'X264')
        now = getTimeStamp()
        outfile = 'out/output.%s.mp4' % (now)
        w = D[0].shape[1]
        h = D[0].shape[0]
        log.debug("out file size: %d %d %d" % (w,h,D[0].size))
        out = cv2.VideoWriter(outfile ,fourcc, FPS, (w,h))
        log.debug("size of deque %d" % len(D))
        for f in D:
            out.write(f)
        out.release()
        log.info("wrote %s" % (outfile))
        ftpQ.put(outfile)


def motion(cap, args, writeQ):
    motionFrameFirst = []
    DRaw = deque(maxlen=args['preframes'])

    while True:
        (retval, rawFrame) = cap.read()

        if not retval:
            log.warning("cap.read() error: %s" % (e))
            time.sleep(1)
            continue

        motionFrame = genMotionFrame(rawFrame)

        if len(motionFrameFirst) == 0:
            motionFrameFirst.append(motionFrame)
            continue
        
        motionDetected = detectMotion(motionFrameFirst[0],
                            motionFrame,
                            args['areaThresh'])

        if motionDetected:
            RawFrames = keepCapturing(motionFrameFirst[0], cap)

            try:
                writeQ.put(deque(list(DRaw)+ RawFrames))
            except Exception as e:
                log.error("Could not put onto writeQ: %s"  % e)

            DRaw.clear()
            motionFrameFirst.pop()

            
if __name__ == "__main__":
    writeQ = queue.Queue()
    ftpQ = queue.Queue()
    args = parseArgs()
    cap = setupCaptureDevice(args)
    if not cap:
        log.error("no capture device could be open")
        sys.exit(5)

    threading.Thread(
            target=writeOut,
            args=(writeQ,ftpQ,),
            daemon=True,
            name='genVid',
            ).start()

    threading.Thread(
            target=ftpOut,
            args=(ftpQ,),
            daemon=True,
            name='ftpOut',
            ).start()
    
    motion(cap, args, writeQ)

