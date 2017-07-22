#! /usr/bin/env python3

import queue
import heapq
import ftplib
from ftplib import FTP
import json
import pprint
import datetime
import sys
import re
import os
import logging

log = logging.getLogger(__name__)

pp = pprint.PrettyPrinter()
'''
loggingFmt='%(asctime)s %(levelname)-8s : %(message)s'
loggingDatefmt='%Y/%m/%d %I:%M:%S'
myformat = logging.Formatter(fmt=loggingFmt,
        datefmt=loggingDatefmt)

logging.basicConfig(filename='LOG',
        format=loggingFmt,
        datefmt=loggingDatefmt,
        level=logging.DEBUG,
        )
ch = logging.StreamHandler()
ch.setFormatter(myformat)
logging.getLogger().addHandler(ch)

'''


class ftpConn():

    def __init__(self,host,user,passwd,wd):
        self.host = host
        self.user = user
        self.passwd = passwd
        self.wd = wd
        self.pp = pprint.PrettyPrinter()
        self.nowUnixTime = int(datetime.datetime.now().strftime("%s"))
        self.connect()
        self.mkdir(self.wd)
        self.cd(self.wd)
        log.info("ftpConn() setup done")

    def quit(self):
        try:
            self.ftp.quit()
            log.info("ftp quit()")
        except Exception as e:
            log.error("ftp quit() error: %s" % e)

    def mkdir(self,d):
        try:
            resp = self.ftp.mkd(d)
            log.info("md: %s" % resp)
        except ftplib.error_perm as e:
            if str(e).startswith('550'):
                log.info("%s exists", d)
            else:
                log.error("UH OH")
        except Exception as e:
            log.error("mkd exception %s"  % (e))

    def cd(self,d):
        try:
            resp = self.ftp.cwd(d)
            log.info("cd: %s" % resp)
        except Exception as e:
            log.error("cd exception: %s" % e)
            sys.exit(3)

    def godir(self,d):
        try:
            resp = self.ftp.cwd(d)
            log.info("cd: %s" % resp)
        except Exception as e:
            self.mkdir(d)
            self.godir(d)

    def uploadFile(self,upfile,path=''):
        log.debug("uploadFile() upfile = %s" % upfile)
        matches = re.search('([^/]+)\/(.+)', upfile)
        if matches:
            log.debug("uploadFile() file needs recursion")
            self.godir(matches.group(1))
            self.uploadFile(matches.group(2),
                        os.path.join(path,matches.group(1)),
                        )
            self.cd('..')
        else:
            filename = upfile
            upfile = os.path.join(path,upfile)
            if not os.path.isfile(upfile):
                log.warning("file not exist: %s" % (upfile))
                return 1
            with open(upfile, 'rb') as f:
                resp = self.ftp.storbinary("STOR %s" % (filename),
                        fp=f
                        )
                log.info("uploadFile resp: %s" % (resp))

    def getFile(self,f):
        log.debug("getFile() f = %s" % f)
        with open(f, 'wb') as fileout:
            def callback(data):
                f.write(data)

            self.ftp.retrbinary('RETR %s' % f, callback)

    def download(self,f,fp):
        log.debug("download() %s" % f)
        self.ftp.retrbinary('RETR ' + f, fp.write)

    def connect(self):
        self.ftp = FTP(host=self.host,
                        user=self.user,
                        passwd=self.passwd,
                        )

    def getUnixTime(self,s):
        return int(datetime.datetime( int(s[0:4]),
                                    int(s[4:6]),
                                    int(s[6:8]),
                                    int(s[8:10]),
                                    int(s[10:12]),
                                    int(s[12:14])
                                ).strftime("%s")
                )

    def rm(self,delFile):
        try:
            resp = self.ftp.delete(delFile)
            log.info("rm() %s" % resp)
        except Exception as e:
            log.error("rm() exception: %s" % e)

    def list(self,d=''):
        FileObjs = self.ftp.mlsd(d)
        fileList = list()
        for fo in FileObjs:
            dotfile = re.search('^(\.+)', fo[0])
            if dotfile:
                continue

            fileList.append(fo[0])

        return fileList

    def listtest(self,d=''):
        FileObjs = self.ftp.mlsd(d)
        for fo in FileObjs:
            try:
                re.search('^(\.+)', fo[0]).group(1)
                log.debug("ignore dotfiles: %s" % fo[0])
                continue
            except Exception as e:
                pass

            log.debug("Filename: %s" % fo[0])
            self.pp.pprint(fo[1])
            fileUnixTime = self.getUnixTime(fo[1]['modify'])
            delta = self.nowUnixTime - fileUnixTime
            log.debug("delta: %d" % delta)
            if delta < FILE_AGE_LIMIT_IN_SECONDS:
                log.info("file is young, keep")
            else:
                log.info("file is old")
                self.rmFile(fo[0])

    def findFiles(self,Q=None,path=''):
        log.debug("findFiles() begin %s" % path)
        if Q == None:
            Q = queue.PriorityQueue()
        FileObjs = self.ftp.mlsd(path)
        for fileObj in FileObjs:
            if fileObj[1]['type'] == 'dir':
                log.debug("findFiles() keep digging %s" % (fileObj[0],))
                self.findFiles(Q,os.path.join(path,fileObj[0]))
            elif fileObj[1]['type'] == 'file':
                log.debug("findFiles() found file %s" % (fileObj[0],))
                fileUnixTime = self.getUnixTime(fileObj[1]['modify'])
                Q.put( (   -fileUnixTime,
                            os.path.join(path,fileObj[0])
                        ) )
            else:
                #log.debug("findFiles() ignore %s" % (fileObj,))
                pass
        
        log.debug("findFiles() done %s" % path)
        return Q

    def rmFiles(ftp,files):
        log.debug("rmFiles()")
        for f in files:
            try:
                ftp.rm(f)
            except Exception as e:
                log.error("rmFiles() ftp.rm() error: %s" % e)

        log.debug("rmFiles() done")



class Creds():
    def __init__(self):
        self.host = ''
        self.user = ''
        self.passwd = ''
        self.getCreds()

    def getCreds(self):
        if os.path.isfile('.creds'):
            with open('.creds', 'r') as f:
                for line in f:
                    toks = line.strip().split('=')
                    if toks[0] == 'host':
                        self.host = toks[1]
                    if toks[0] == 'user':
                        self.user= toks[1]
                    if toks[0] == 'passwd':
                        self.passwd= toks[1]

    #FILE_AGE_LIMIT_IN_DAYS = 14
    #FILE_AGE_LIMIT_IN_SECONDS = 60 * 60 * 24 * FILE_AGE_LIMIT_IN_DAYS
def rmOldFiles(ftp,limitSeconds=60*60*24*7):
    log.debug("rmOldFiles() limit = %d" % limitSeconds)
    Q = ftp.findFiles()
    now = int(datetime.datetime.now().strftime("%s"))
    log.debug("queue size: %d" % Q.qsize())
    while Q.qsize() > 0:
        try:
            fileTime,f = Q.get(False,5)
        except Exception as e:
            log.error("rmOldFiles() could not Q.get(): %s" % e)
            return
        # we store unix time as negative in min heap 
        #   for oldest-file-first sorting
        if now + fileTime > limitSeconds:
            log.info("rmOldFiles() rm %s" % (f,))
            try:
                ftp.rm(f)
            except Exception as e:
                log.error("rmOldFiles() ftp.rm() error: %s" % e)
        else:
            log.debug("rmOldFiles() keep %s" % (f,))

    log.debug("rmOldFiles() done")


if __name__ == '__main__':
    c = Creds()
    wd = "public_html/python_test/"
    ftp = ftpConn(c.host,c.user,c.passwd,wd)


