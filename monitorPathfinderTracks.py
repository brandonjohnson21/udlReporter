# #######################################
# Default monitor.yml
# #######################################
# query configuration
# queries:
#   - /api/path?ts={lastts}..{currentts}
#   - /api/path2?ts={lastts}..{currentts}&moreArgs=true

# host: https://localhost:8080

# # email configuration
# sender: test@test.com
# recipients: 
#   - test1@test.com
#   - test2@test.com
#   - test3@test.com
# smtp: localhost

# # number of tracks returned to be considered "good"
# minimumSinceLast: 10000
# # interval between checks in seconds
# interval: 3600

# # how many failed checks until an email is sent
# failuresUntilEmail: 1
# # whether to continue to send emails every check before restoral
# sendEmailEveryTime: False

# ########################################
    # Will read REST username from UDL_USR
    # Will read REST password from UDL_PWD
    # Will read SMTP username from SMTP_USR
    # Will read SMTP password from SMTP_PWD
# ########################################

import smtplib
import yaml
import os
import sys
import requests
import datetime
import time
import getopt

# setup globals
user = None
pwd = None
suser = None
spwd = None
lastTime = None
hasMailed = False
failcount = 0
settings = None
# get arguments
try:
    opts, args = getopt.getopt(
        sys.argv[1:],
        "u:p:",
        ["usr=", "pwd=", "smtpusr=", "smtppwd="])
except getopt.GetoptError:
    print('monitor.py -u username -p password --smtpusr=username --smtppwd=password')
    sys.exit(2)


for opt, arg in opts:
    if opt in ("-u", "--usr"):
        user = arg
    elif opt in ("-p", "--pwd"):
        pwd = arg
    elif opt in ("--smtpusr"):
        suser = arg
    elif opt in ("--smtppwd"):
        spwd = arg


if (user is None):
    user = os.environ.get('UDL_USR')
if (pwd is None):
    pwd = os.environ.get('UDL_PWD')
if ((user is None or pwd is None)):
    print("User or pass not provided")
    sys.exit(2)

if (suser is None):
    suser = os.environ.get('SMTP_USR')
if (spwd is None):
    spwd = os.environ.get('SMTP_PWD')
if ((suser is None or spwd is None)):
    print("WARN: SMTP User or pass not provided")


def validateSettings():
    global settings
    noErrors = True
    with open(r'./monitor.yml') as file:
        settings = yaml.full_load(file)
        file.close()
    if (settings.get("queries") is None):
        print("ERROR: queries missing from monitor.yml")
        settings["querties"] = ["/path/to/endpoint"]
        noErrors = False
    if (settings.get("host") is None):
        print("ERROR: host missing from monitor.yml")
        settings["host"] = "https://localhost"
        noErrors = False
    if (settings["host"].endswith('/')):
        print("WARN: host entered with / as last character")
    if (settings.get("interval") is None):
        print("ERROR: interval missing from monitor.yml")
        settings["interval"] = 3600
        noErrors = False
    if (settings.get("failuresUntilEmail") is None):
        print("ERROR: failuresUntilEmail missing from monitor.yml")
        settings["failuresUntilEmail"] = 3
        noErrors = False
    if (settings["failuresUntilEmail"] < 1):
        print("ERROR: invalid setting failuresUntilEmail is "+str(settings["failuresUntilEmail"]))
        settings["failuresUntilEmail"] = 3
        noErrors = False
    if (settings.get("sendEmailEveryTime") is None):
        print("ERROR: sendEmailEveryTime missing from monitor.yml")
        settings["sendEmailEveryTime"] = False
        noErrors = False
    if (settings.get("sender") is None):
        print("ERROR: sender missing from monitor.yml")
        settings["sender"] = "emailFrom@email.com"
        noErrors = False
    if (settings.get("recipients") is None):
        print("ERROR: recipients missing from monitor.yml")
        settings["recipients"] = ["emailTo@email.com"]
        noErrors = False
    if (settings.get("smtp") is None):
        print("ERROR: smtp missing from monitor.yml")
        settings["smtp"] = "localhost"
        noErrors = False
    return noErrors

if (os.path.isfile("./monitor.yml") is not True):
    print("Missing monitor.yml")
    sys.exit(2)
if (os.path.isfile("./failemail.txt") is not True):
    print("Missing failemail.txt")
    sys.exit(2)
with open("./failemail.txt", "r") as file:
    failMessage = file.read()
    file.close()

if (os.path.isfile("./restoreemail.txt") is not True):
    print("Missing restoreemail.txt")
    print("Will not send restoral email")
    sys.exit(2)
else:
    with open("./restoreemail.txt", "r") as file:
        restoreMessage = file.read()
        file.close()


if (validateSettings() is not True):
    print("Missing options in monitor.yml file")
    with open('./monitor.yml', 'w') as file:
        yaml.dump(settings, file)
        file.close()
    sys.exit(2)


def runQuery():
    global lastTime
    global hasMailed
    global failcount
    currentTime = datetime.datetime.utcnow()
    total = 0
    successfulChecks = 0
    for query in settings["queries"]:
        url = settings["host"] + query
        url = url.replace("{lastts}", lastTime.isoformat() + "Z")
        url = url.replace("{currentts}", currentTime.isoformat() + "Z")
        print(url)
        count = 0
        result = requests.get(url, auth=requests.auth.HTTPBasicAuth(user, pwd))
        if (result.status_code >= 400):
            print("Failed to retrieve data from server.")
            print("Status: " + str(result.status_code) + " " + result.reason)
            continue
        if (result.headers['content-type'].find("application/json") >= 0):
            try:
                jData = result.json()
                if (isinstance(jData, list)):
                    count = len(jData)
                    print("Received " + str(count) + " entries.")
                    successfulChecks += 1
                else:
                    print("Data returned was not an array.")
                    continue
            except:
                continue
        else:
            try:
                count = int(result.text)
                print("Received " + str(count) + " entries.")
                successfulChecks += 1
            except:
                continue
        total += count
    if (successfulChecks < 1):
        return
    if (total < settings["minimumSinceLast"]):
        failcount += 1
    else:
        failcount = 0
    if (hasMailed and failcount == 0):
        hasMailed = not email({
            "time": currentTime.isoformat()+"Z",
            "count": str(total),
            "failed": False})

    if (failcount >= settings["failuresUntilEmail"] and (not hasMailed or settings["sendEmailEveryTime"])):
        hasMailed = email({
            "time": currentTime.isoformat()+"Z",
            "count": str(total),
            "failed": True})
    lastTime = currentTime


def email(emailData):
    try:
        if (emailData["failed"]):
            msg = failMessage
        else:
            if (restoreMessage is None):
                return
            msg = restoreMessage
        msg = msg.replace("{sender}", settings["sender"])
        msg = msg.replace("{count}", emailData["count"])
        msg = msg.replace("{time}", emailData["time"])
        msg = msg.replace("{required}", str(settings["minimumSinceLast"]))
        smtpObj = smtplib.SMTP('localhost')
        if (suser is not None and spwd is not None):
            try:
                smtpObj.starttls()
                server.login(suser, spwd)
            except smtplib.SMTPNotSupportedError:
                print("SMTP server does not support TTLS")
            except:
                print("Unknown SMTP authentication error")
        smtpObj.sendmail(settings["sender"], settings["recipients"], msg)
        print("Successfully sent email")
    except smtplib.SMTPException:
        print("Error: unable to send email")
        return False
    return True

lastTime = datetime.datetime.utcnow() - datetime.timedelta(seconds=settings["interval"])


while True:
    validateSettings()
    runQuery()
    time.sleep(settings["interval"])
