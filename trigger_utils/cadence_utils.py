import numpy as np
import pandas as pd
from astropy.time import Time, TimeDelta
from trigger_utils import update_trigger_log, check_executed_observation, send_trigger_email

class MyException(Exception):
    pass

def check_pending_observations(df):
    """
    Check if we have pending observations
    """
    check_pending = []

    for row in df.itertuples(index=False):
        if row.valid != 'True':
            continue
        pending = row.pending_observation
        if pd.isna(pending):
            continue
        supereventid = row.superevent_id
        items = pending.split('),(')
        items_list = [
            (int(item.split(",")[0].strip("()")), item.split(",")[1].strip("()"))
            for item in items
        ]
        print(f'Found {len(items_list)} pending observation for {supereventid}')
        current_date = Time.now()
        for item in items_list:
            observation_plan_id, start_observation = item[0], item[1]
            #if it is before the time for observation, don't do anything yet
            if current_date < Time(start_observation):
                print(f'Observation of {supereventid} scheduled for {start_observation} - will check tomorrow')
                continue
            # if the current date is within 2 days after start_observation, check if we observed
            time_difference = abs((current_date - Time(start_observation)).jd)
            if time_difference <= 2:
                gcnid = row.gcn_id 
                localizationid = row.localization_id
                dateobs = row.dateobs
                print(f'will check status of pending observation for {supereventid} on {start_observation}')
                format_item = f"({item[0]},{item[1]})"
                check_pending.append([True, supereventid, format_item, gcnid, localizationid, observation_plan_id, dateobs])
            else:
                # this will make event be moved to unsuccessful observation
                check_pending.append([False, supereventid, pending, None, None, None, None])
    return check_pending

def parse_pending_observation(path_data, fritz_token, mode):
    #open log of triggers
    trigger_log = pd.read_csv(
        f'{path_data}/trigger_data/triggered_events.csv', 
        dtype={
            "gcn_id": "Int64",
            "localization_id": "Int64"
        }
    )
    retry = []
    pending = check_pending_observations(trigger_log)
    if pending:
        for x in pending:
            try:
                within_time = x[0]
                superevent_id = x[1]
                observation_info = x[2]
                gcnid = x[3]
                localizationid = x[4]
                observation_plan_id = x[5]
                dateobs = x[6]
                if not within_time:
                    # ~2 days post trigger and still unsuccessful - handle manually
                    update_trigger_log(superevent_id, 'unsuccessful_observation', observation_info, append_string=True)
                    update_trigger_log(superevent_id, 'pending_observation', observation_info, remove_string=True)
                    print(f'We did not sucessfully observe the queued plans for {superevent_id}')
                    continue
                enddate = (Time(dateobs) + TimeDelta(3, format='jd')).iso
                # TODO: replace check_executed_observation
                observations = check_executed_observation(dateobs, enddate, gcnid, fritz_token, mode)
                if observations['data']['totalMatches'] >= 1:
                    print(f'Observation of {superevent_id} successful')  
                    update_trigger_log(superevent_id, 'successful_observation', observation_info, append_string=True)
                    update_trigger_log(superevent_id, 'pending_observation', observation_info, remove_string=True)
                else:
                    retry.append(['retry', superevent_id, gcnid, localizationid, dateobs]) 
                    print(f"Trigger not successful for {superevent_id} - retrying for tonight")

            except MyException as e:
                print(e)
                continue
    return retry


def trigger_on_cadence(path_data):
    """
    Follow-up triggers based on trigger_cadence
    times in UTC time
    """

    df = pd.read_csv(
        f'{path_data}/trigger_data/triggered_events.csv', 
        dtype={
            "gcn_id": "Int64",
            "localization_id": "Int64"
        }
    )
    df["gcn_id"] = df["gcn_id"].astype("int", errors="ignore")
    df["localization_id"] = df["localization_id"].astype("int", errors="ignore")

    trigger = []
    for row in df.itertuples(index=False):
        if row.valid != 'True':
            continue
        cadence_str = row.trigger_cadence
        cadence = cadence_str.strip("[]").replace("'", "").split(", ")
        current_date = Time.now().strftime('%Y-%m-%d')
        for cadence_date in cadence:
            if Time(current_date) == Time(cadence_date):
                supereventid = row.superevent_id
                gcnid = row.gcn_id 
                localizationid = row.localization_id
                dateobs = row.dateobs
                trigger.append(['followup', supereventid, gcnid, localizationid, dateobs]) 
                print(f"Found follow-up trigger: {supereventid} on {cadence_date}")
    return trigger  