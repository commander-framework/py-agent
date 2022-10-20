import asyncio
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from multiprocessing import Process
import os
from platform import system
import requests
import shutil
from socket import gethostname
import ssl
import subprocess
import sys
import tempfile
from utils import utcNowTimestamp
import websockets
import zipfile


def resourcePath(relativePath):
    """ Get absolute path to resource, works in and out of PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        basePath = sys._MEIPASS
    except Exception:
        basePath = os.path.abspath(".")
    return os.path.join(basePath, relativePath)


class CommanderAgent:
    def __init__(self, agentID="", appName="", serverAddress="", registrationKey="", logLevel=4):
        self.appName = appName
        self.os = system()
        self.log = self.logInit(logLevel)
        self.clientCert = (resourcePath("agentCert.crt"), resourcePath("agentKey.pem"))
        self.serverCert = resourcePath("commander.crt")
        self.commanderServer = serverAddress
        self.registrationKey = registrationKey
        if self.registrationKey:
            self.agentID = self.register()
        else:
            self.agentID = agentID
        self.headers = {"Content-Type": "application/json",
                        "agentID": self.agentID}
        self.exitSignal = False
        self.jobQueue = asyncio.Queue()
        self.runningJobs = []
        self.connectedToServer = False

    def logInit(self, logLevel):
        """ Configure log level (1-5) and OS-dependent log file location """
        # set log level
        level = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL][5-logLevel]
        logging.basicConfig(level=level, format="%(levelname)-8s: %(message)s")
        log = logging.getLogger("CommanderAgent")
        formatter = logging.Formatter(fmt="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
                                      datefmt="%Y-%m-%d %H:%M:%S")
        if self.os == "Linux" or self.os == "Darwin":
            handler = TimedRotatingFileHandler(filename="/var/log/commander.log",
                                                   encoding="utf-8",
                                                   when="D",  # Daily
                                                   backupCount=7)
        elif self.os == "Windows":
            handler = TimedRotatingFileHandler(filename="commander.log",
                                                   encoding="utf-8",
                                                   when="D",  # Daily
                                                   backupCount=7)
        handler.setFormatter(formatter)
        log.addHandler(handler)
        return log

    def request(self, method, directory, body=None, headers=None, files=None):
        """ HTTPS request to Commander server using client and server verification """
        if headers is None:
            headers = self.headers
        if body is None:
            body = {}  # set here to prevent mutating default arg
        if files is None:
            files = {}
        try:
            if method == "GET":
                response = requests.get(f"https://{self.commanderServer}{directory}",
                                        headers=headers,
                                        cert=self.clientCert,
                                        verify=self.serverCert,
                                        data=json.dumps(body))
            elif method == "POST":
                response = requests.post(f"https://{self.commanderServer}{directory}",
                                        headers=headers,
                                        cert=self.clientCert,
                                        verify=self.serverCert,
                                        data=json.dumps(body),
                                        files=files)
            elif method == "PUT":
                response = requests.put(f"https://{self.commanderServer}{directory}",
                                        headers=headers,
                                        cert=self.clientCert,
                                        verify=self.serverCert,
                                        data=json.dumps(body),
                                        files=files)
            elif method == "DELETE":
                response = requests.delete(f"https://{self.commanderServer}{directory}",
                                        headers=headers,
                                        cert=self.clientCert,
                                        verify=self.serverCert,
                                        data=json.dumps(body),
                                        files=files)
            else:  # method == "PATCH":
                response = requests.patch(f"https://{self.commanderServer}{directory}",
                                        headers=headers,
                                        cert=self.clientCert,
                                        verify=self.serverCert,
                                        data=json.dumps(body),
                                        files=files)
            self.connectedToServer = True
        except requests.exceptions.RequestException as e:
            # log failure
            self.log.warning(f"Unable to contact server: {e}")
            self.connectedToServer = False
        except Exception as e:
            self.log.critical(f"Unhandled error while sending a request to the server: {e}")
        return response

    def register(self):
        """ Register agent with the commander server or fetch existing configuration """
        if not self.registrationKey:
        # contact server and register agent
            self.log.critical("No registration key provided")
            sys.exit(1)
        response = self.request("POST", "/agent/register",
                                headers={"Content-Type": "application/json"},
                                body={"registrationKey": self.registrationKey,
                                        "hostname": gethostname(),
                                        "os": self.os})
        # create config and save to disk
        if "error" in response.json():
            self.log.error("HTTP"+str(response.status_code)+": "+response.json()["error"])
        configJson = {"appName": self.appName,
                      "agentID": response.json()["agentID"],
                      "serverAddress": self.commanderServer,
                      }
        with open("agentConfig.json", "w") as configFile:
            configFile.write(json.dumps(configJson))
        return response.json()["agentID"]

    async def checkIn(self):
        """ Check in with the commander server to see if there are any jobs to run """
        # TODO: break this out into a separate class to allow for modular checkin methods
        sslContext = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        sslContext.load_verify_locations(self.caPath)
        sslContext.load_cert_chain(certfile=self.cert[0], keyfile=self.cert[1])
        while True:
            try:
                async with websockets.connect(f"wss://{self.commanderServer}/agent/checkin", ssl=sslContext) as ws:
                    self.connectedToServer = True
                    self.log.info("Connected to server. Listening for jobs...")
                    await ws.send(json.dumps({"Agent-ID": self.agentID}))
                    self.getJobs(ws)
            except websockets.exceptions.ConnectionClosed:
                self.connectedToServer = False
                self.log.info("Connection to server closed. Attempting to reconnect...")
            except Exception as e:
                self.connectedToServer = False
                self.log.error(f"Error connecting to websocket server: {e}")

    async def getJobs(self, ws):
        """ Receive one or more jobs from the websocket """
        while not self.exitSignal:
            try:
                jobs = await asyncio.wait_for(ws.recv(), timeout=1)
                jobs = json.loads(jobs)
            except asyncio.exceptions.TimeoutError:
                jobs = None
            if jobs:
                await ws.send("ack")
                self.log.info(f"Received {len(jobs)} jobs")
                for job in jobs:
                    self.jobQueue.put(job)
                    self.log.debug(f"Job {job['jobID']} added to worker queue")

    async def worker(self):
        """ Check the queue for jobs """
        while not self.exitSignal:
            try:
                job = await self.jobQueue.get()
            except asyncio.exceptions.TimeoutError:
                job = None
            if job:
                self.log.debug(f"Worker received job {job['jobID']} from the worker queue")
                task = Process(target=self.doJob, args=(job,))
                task.start()
                self.runningJobs.append(task)
    
    def doJob(self, job):
        """ Fetch the job package and start execution """
        # TODO: break this out into a separate class to allow for modular execution types
        response = self.request("GET", "/agent/execute",
                                headers={"Content-Type": "application/json",
                                         "Agent-ID": self.agentID},
                                body={"filename": job["filename"]})
        with open(f"{tempfile.gettempdir()}/{job['filename']}.job", "wb") as jobPackage:
            jobPackage.write(response.content)
        self.execute(job)

    def execute(self, job):
        """ Execute the given job package and start cleanup """
        # parse manifest and extract zip archive
        with zipfile.ZipFile(f"{tempfile.gettempdir()}/{job['filename']}.job", "r") as jobPackage:
            jobPackage.extractall(path=f"{tempfile.gettempdir()}/{job['jobID']}")
        # execute job
        commandline = []
        if job["executor"] != "binary":
            commandline.append(job['executor'])
        commandline.append(f"{tempfile.gettempdir()}/{job['jobID']}/{job['filename']}")
        commandline = commandline + [arg for arg in job['argv']]
        job["timeStarted"] = utcNowTimestamp()
        result = subprocess.Popen(commandline, capture_output=True)
        # capture output and clean up
        stdout, stderr = result.communicate()
        job["timeEnded"] = utcNowTimestamp()
        job["exitCode"] = result.returncode
        job["stdout"] = stdout.decode("utf-8")
        job["stderr"] = stderr.decode("utf-8")
        self.cleanup(job)

    def cleanup(self, job):
        """ Send execution status back to commander server and delete the job package """
        response = self.request("POST", "/agent/history",
                                headers={"Content-Type": "application/json",
                                         "Agent-ID": self.agentID},
                                body={"job": job})
        if response.status_code != 200:
            self.log.error(f"Error when reporting job execution status: {response.status_code} -- {response.json['error']}")
            # save job to disk for later reporting
            if not os.path.exists("ReportsQueue"):
                os.mkdir("ReportsQueue")
            with open(f"ReportsQueue/{job['jobID']}.json", "w") as f:
                f.write(json.dumps(job))
            return
        self.log.info(f"Job {job['jobID']} completed successfully")
        # delete job package
        shutil.rmtree(f"{tempfile.gettempdir()}/{job['jobID']}")
        os.remove(f"{tempfile.gettempdir()}/{job['filename']}.job")

    async def garbageCollector(self):
        """ Clean up finished jobs and remediate failed tasks """
        while not self.exitSignal:
            # remove completed jobs from the running jobs list
            for process in self.runningJobs:
                if not process.is_alive():
                    self.runningJobs.remove(process)
            # retry sending reports for jobs that failed to report
            if os.path.exists("ReportsQueue"):
                reports = [item for item in os.listdir("ReportsQueue") if os.path.isfile(item)]
                for report in reports:
                    with open(f"ReportsQueue/{report}", "r") as f:
                        job = json.loads(f.read())
                    self.cleanup(job)
            await asyncio.sleep(30)

    def run(self):
        """ Start agent """
        asyncio.gather(self.checkIn(), self.worker(), self.garbageCollector())
