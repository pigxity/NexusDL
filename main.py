import curl_cffi
import requests
import json
from time import sleep
import os
import time
import threading
import math
from tkinter import Tk
from classes import *

# nexus has both numerical and text game ids, this converts the gameName in modlist to both ids.
with open('gamemap.json', 'r') as f:
    gameToId = json.load(f)

defaultConfig = """{
    "cache_file": "./downloadedmods.json",
    "download_dir": "./download",
    "temp_dir": "./temp",
    "modlist_file": "./modlist",
    "threads": 4,

    "nexus_sessions": [
        "your nexus session token goes here"
    ],
    "multi_sessions": false
}"""

configFile = "./config.json"

if not os.path.exists(configFile):
    with open(configFile, "w") as f:
        f.write(defaultConfig)
    input("The default config file for NexusDL has been created. Please edit it to include your NexusMods session token.")
    exit()

with open(configFile, "r") as f:
    config = json.loads(f.read())

downloadDir = config['download_dir']
tempDir = config['temp_dir']
urlcacheFile = config['cache_file']
maxThreads = config['threads']
nexusSessions = config['nexus_sessions']
useMultiSession = config['multi_sessions']
modlistFile = config['modlist_file']

if not os.path.exists(tempDir):
    os.makedirs(tempDir)
if not os.path.exists(downloadDir):
    os.makedirs(downloadDir)


def getDownloadUrl(fileid, gameid, threadNum):
    if not useMultiSession:
        threadNum = 0
    apiurl = "https://www.nexusmods.com/Core/Libs/Common/Managers/Downloads?GenerateDownloadUrl"
    cookies = {"nexusmods_session": nexusSessions[threadNum]}
    resp = curl_cffi.post(apiurl, impersonate="chrome", cookies=cookies, data={
        "fid": fileid,
        "game_id": gameid
    })
    if resp.status_code == 200:
        return resp.json()["url"]#.split('&user_id')[0]
    else:
        print(cookies)
        print(resp.status_code)
        print(resp.text)
        exit()

def downloadFile(url, fileid, filename, threadNum):
    global gui
    actualThreadNum = threadNum
    if not useMultiSession:
        threadNum = 0
    #global threadStatus
    cookies = {"nexusmods_session": nexusSessions[threadNum]}
    sleep(2)
    while True:
        response = requests.get(url, stream=True, cookies=cookies)
        if response.status_code == 200:
            #filename = url.split('/')[-1].split('?')[0] # extract filename from url

            filesize = int(response.headers.get('Content-Length', 0))
            filepath = os.path.join(tempDir, filename)

            print("Downloading File: " + filename)

            progress_bar = gui.threadProgress[actualThreadNum]
            progress_bar["maximum"] = filesize

            with open(filepath, "wb") as file:
                downloaded_size = 0
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        file.write(chunk)

                        downloaded_size += len(chunk)

                        progress_bar["value"] = downloaded_size
                        updateThreadStatus(actualThreadNum, f"Downloading: {filename} - {(downloaded_size / filesize) * 100:.2f}%")

            os.replace(filepath, os.path.join(downloadDir, filename))
            break
        else:
            print(f"{response.status_code}: Unable to download file: {response.text}")
            print(url)
            exit()
            break

with open(modlistFile) as f:
    modlist = json.loads(f.read())['Archives']

UrlCacheErrored = False
#threadStatus = [None] * maxThreads
gui = ProgressBarGUI(threadCount=maxThreads, totalmodcount=len(modlist))

def updateThreadStatus(threadNum, text):
    global gui
    label = gui.threadLabels[threadNum]
    label.config(text=f"{threadNum + 1}: {text}")

def downloadModThread(mods, urlcache, start_index, end_index, totalmods, threadNum):
    for i in range(start_index, end_index):
        mod = mods[i]
        state = mod['State']

        if not 'NexusDownloader' in state['$type']:
            continue

        modcache = urlcache.get(str(state['ModID']))
        if modcache:
            if modcache['downloaded'] == True:
                print(f"Skipping mod {state['Name']} - Mod already downloaded")
                gui.modsDownloaded += 1
                gui.updateTotalMods()
                continue

        updateThreadStatus(threadNum, f"Fetching URL: {state['Name']}")
        
        nexusGameId = gameToId[state['GameName']]
        try:
            print(f"Mod: {i + 1}/{totalmods} - {state['Name']}")

            downloadUrl = getDownloadUrl(state['FileID'], nexusGameId, threadNum)
            updateThreadStatus(threadNum, f"Downloading Mod: {state['Name']}")
            downloadFile(downloadUrl, state['FileID'], mod['Name'], threadNum)
            urlcache[state['ModID']] = ({"url": downloadUrl, "downloaded": True})

            with open(urlcacheFile, 'w') as f:
                json.dump(urlcache, f)
            
            gui.modsDownloaded += 1
            gui.updateTotalMods()

        except Exception as e:
            updateThreadStatus(threadNum, f"An error occurred while downloading mod {state['Name']}: {e}")
            urlcache[state['ModID']] = ({"url": "ERROR", "downloaded": False})
            global UrlCacheErrored
            UrlCacheErrored = True
            exit()

def downloadMods(modlist):
    urlcache = {}
    if os.path.exists(urlcacheFile):
        with open(urlcacheFile, "r") as f:
            urlcache = json.loads(f.read())

    totalmods = len(modlist)
    newModlist = []

    for i in range(totalmods):
        mod = modlist[i]
        state = mod['State']
        
        if not 'NexusDownloader' in state['$type']:
            continue

        cache = urlcache.get(str(state['ModID']))

        if cache:
            if cache['downloaded'] == True:
                print(f"Skipping mod {state['Name']}")
                continue

        newModlist.append(mod)

    totalmods = len(newModlist)
    modsPerThread = totalmods // maxThreads
    remainder = totalmods % maxThreads

    gui.totalmodcount = totalmods

    # Calculate how many mods each thread will process
    threadMods = [modsPerThread + (1 if i < remainder else 0) for i in range(maxThreads)]

    threads = []
    currentmod = 0

    print("Downloading mods")
    for i in range(maxThreads):
        start_index = currentmod
        end_index = start_index + threadMods[i]

        threadNum = i
        thread = threading.Thread(target=downloadModThread, args=(newModlist, urlcache, start_index, end_index, totalmods, threadNum))

        threads.append(thread)
        thread.start()
        #threadStatus[threadNum] = "Starting"
        currentmod = end_index  # Update the current mod index

    # while waiting for threads, create graphical progress interface
    gui.mainloop(threads)

    # join threads
    for thread in threads:
        thread.join()

    with open(urlcacheFile, 'w') as f:
        json.dump(urlcache, f)

    print("Finished creating url cache file")

downloadMods(modlist)