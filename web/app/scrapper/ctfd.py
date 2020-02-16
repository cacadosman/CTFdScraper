#!/usr/bin/env python
from threading import Thread, Lock
from requests import session
from argparse import Namespace
from bs4 import BeautifulSoup
from flask import jsonify
import logging as log
import requests, json
import sys, os
import re, time

try:
   import queue
except ImportError:
   import Queue as queue

class CTFdScrape(object):
    __userAgent = 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36'

    def __init__(self, team, passwd, url, path):
        self.auth    = dict(name=team, password=passwd)
        self.url     = url.strip('/')
        self.dlSize  = 0.0
        self.chcount = 0
        self.files   = []
        self.starTim = time.time()
        self.override  = True
        self.dl_file   = True
        self.__setEnVar()

        if not self.__login():
            raise Exception('Login Failed')
        
        self.__manageVersion()

        self.path = os.path.join(os.getcwd(), path, self.title)
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        os.chdir(self.path)
        
    def __setEnVar(self):
        # CTFd params
        self.keys    = 'data'
        self.version = 'v.1.0'
        self.entry   = dict(url=self.url, data={})
       
        # Persistent session
        self.ses     = session()
        self.ses.headers.update({'User-Agent' : self.__userAgent})
       
        # CTFd Endpoint
        self.ch_url  = self.url + '/api/v1/challenges'
        self.hi_url  = self.url + '/api/v1/hints'
        self.lg_url  = self.url + '/login'
        
        # Other
        self.regex   = re.compile(r'(\/files\/)?([a-f0-9]*\/.*\.*\w*)')
        self.escape  = re.compile(r'[\\\/\:\*\?\"\<\>\|(\s\.)\.]')
        self.travers = True

        #Logging
        log.basicConfig(filename='error.log', level=log.INFO)

    def __login(self):
        try:
          resp  = self.ses.get(self.lg_url)
          soup  = BeautifulSoup(resp.text,'lxml')
          nonce = soup.find('input', {'name':'nonce'}).get('value')
          self.auth['nonce'] = nonce
          self.title = soup.title.string
          resp  = self.ses.post(self.lg_url, data=self.auth)
          return 'incorrect' not in resp.text
        except Exception as e:
          log.exception(str(e) + '\n')

    def __manageVersion(self):
        resp = self.ses.get(self.ch_url)
        if '404' in resp.text:
            self.keys    = 'game'
            self.version = 'v.1.2.0'
            self.ch_url  = self.url + '/chals'
            self.hi_url  = self.url + '/hints'
            self.sol_url = self.ch_url + '/solves'

    def __getHintById(self, id):
        resp = self.ses.get('%s/%s' % (self.hi_url,id)).json()
        return resp['data']['content']

    def __getHints(self, data):
        res = [] 
        for hint in data:
            if hint['cost'] == 0:
                if self.version != 'v.1.2.0':
                    res.append(self.__getHintById(hint['id']))
                else:
                    res.append(hint['hint'])
        return res

    def __getSolves(self, data):
        if self.version != 'v.1.2.0':
            return data['solves']
        else:
            try:
                return self.solves[str(data['id'])]
            except:
                self.solves = self.ses.get(self.sol_url).json()
                return self.solves[str(data['id'])]

    def __getChallById(self, id):
        try:
          resp = self.ses.get('%s/%s' % (self.ch_url,id)).json()
          return self.__parseData(resp['data'])
        except Exception as e:
          log.exception(str(e) + '\n') 

    def __getChall(self, q):
        while not q.empty():
            id = q.get()
            if self.version != 'v.1.2.0':
                self.chals[id] = self.__getChallById(id)
            else:
                try:
                  if self.traverseable:
                    self.chals[id] = self.__getChallById(id)
                  else:
                    self.chals[id] = self.__parseData(self.chals[id])
                except:
                  self.traverseable = False
                  self.chals[id] = self.__parseData(self.chals[id])

            self.chals.pop(id) if not self.chals[id] else None
            q.task_done()
        return True

    def __parseData(self, data):
        if data:
          entry = {
            'id'          : data['id'],
            'name'        : data['name'],
            'name'        : self.escape.sub('', data['name']),
            'points'      : data['value'],
            'description' : data['description'],
            'files'       : data['files'],
            'category'    : data['category'],
            'category'    : self.escape.sub('', data['category']),
            'solves'      : self.__getSolves(data),
            'hints'       : self.__getHints(data['hints'])
          }
          # print(json.dumps(entry, sort_keys=True, indent=4))
          self.chcount += 1
          return entry

    def __download(self, q):
        while not q.empty():
            path, url = q.get()
            filename  = url.split('/')[-1].split('?')[0]
            path = os.path.join(path,filename)
            if (not os.path.exists(path) or self.override) and not self.dl_file:
                try:
                    resp = self.ses.get(self.url + '/files/' + url, stream=True)
                    with open(path, 'wb') as handle:
                        for chunk in resp.iter_content(chunk_size=512):
                            if chunk:
                                handle.write(chunk)
                    self.dlSize  += int(resp.headers.get('Content-Length', 0))
                except Exception as e:
                    log.exception(str(e) + '\n')
            q.task_done()

        return True
        
    def __populate(self, q):
        while not q.empty():
            vals = self.chals[q.get()]
            ns   = Namespace(**vals)

            path = os.path.join(self.path, ns.category, ns.name)
            if not os.path.exists(path):
                os.makedirs(path)

            with open(os.path.join(path, 'README.md'),'wb') as f:
                desc  = ns.description.encode('utf-8').strip()
                name  = ns.name.encode('utf-8').strip()
                cat   = ns.category.encode('utf-8').strip()
                solve = str(ns.solves).encode('utf-8').strip()
                hint  = '\n* '.join(ns.hints).encode('utf-8')
                cont  = '# %s [%s pts]\n\n' % (name, ns.points)
                cont += '**Category:** %s\n' % (cat)
                cont += '**Solves:** %s\n\n' % (solve)
                cont += '## Description\n>%s\n\n' % (desc)
                cont += '**Hint**\n* %s\n\n' % (hint)
                cont += '## Solution\n\n'
                cont += '### Flag\n\n'

                if sys.version_info.major == 2:
                    f.write(cont)
                else:
                    cont = re.sub(r"(b\')|\'",'',cont)
                    f.write(bytes(cont.encode()))

            self.files += [(path, self.regex.search(i).group(2)) for i in ns.files]
            data = self.entry['data'].get(ns.category, list())
            if not data:
                self.entry['data'][ns.category] = data
            data.append(vals)
            q.task_done()

        return True

    def __listChall(self, sp):
        for key,val in self.entry['data'].items():
            sp.start('{0:<20}({1:<0})'.format(key, len(val)))
            sp.succeed()

    def __Threader(self, elements, action=None, nodes=3):
        que = queue.Queue()
        [que.put(_) for _ in elements]

        for i in range(nodes):
            worker = Thread(target=action, args=(que, ))
            worker.setDaemon(True)
            worker.start()
        que.join()
        del que

    def getChallenges(self):
        # with Halo(text='\n Collecting challs') as sp:
        challs      = self.ses.get(self.ch_url).json()[self.keys]
        challs      = sorted(challs, key=lambda _: _['category']) 
        self.chals  = {ch['id'] : ch for ch in challs}
        # sp.succeed('Found %s challenges'%(len(self.chals)))
        return True

    def createArchive(self):
        # with Halo(text='\n Downloading Assets') as sp:
        self.__Threader(self.chals, self.__getChall,1)
        self.__Threader(self.chals, self.__populate)
        self.__Threader(self.files, self.__download)
        print('Downloaded {0:} files ({1:.2f} MB)'.format(len(self.files),self.dlSize/10**6))
        # sp.succeed('Downloaded {0:} files ({1:.2f} MB)'.format(len(self.files),self.dlSize/10**6))

    def review(self):
        # print('\n[Summary]')
        # self.__listChall(Halo())
        # print('\n[Finished in {0:.2f} second]'.format(time.time() - self.starTim))
        with open('challs.json','wb') as f:
            data = json.dumps(self.entry ,sort_keys=True, indent=4)
            if sys.version_info.major == 2:
                f.write(data)
            else:
                f.write(bytes(data.encode()))

# TODO
# Add Scoreboard (Image / CLI?)
# Add Cloud Dowloader (Dropbox, Mega.nz, Google Drive)
# Add Markdown for challs hierarchy
# Add more argument (override files, challs only, force-download,)