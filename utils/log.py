import datetime
import time
import os

LOG_DIR = "data/logs"
verbose = True

def time_stamp():
    """

    :return: UTC time -> string
    """
    return datetime.datetime.utcnow().strftime("%Y%m%d_%H:%M:%S")


def log(message):
    if verbose:
        timestamp = time_stamp()
        print(f"{timestamp}: {message}")

    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)

    date = timestamp.split("_")[0]
    with open(os.path.join(LOG_DIR, f"bbhbot_{date}.log"), "a") as logfile:
        logfile.write(f"{timestamp}: {message}\n")
        logfile.flush()

def heartbeat():
    while True:
        log('heartbeat')
        time.sleep(60)

