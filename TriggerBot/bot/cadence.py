from cadence_utils import *
from trigger_utils import *
import yaml
import time

with open('TriggerCredentials.yaml', 'r') as file:
    credentials = yaml.safe_load(file)
testing = credentials['testing']

#choose whether we use preview.fritz or fritz api
if testing:
    mode = 'preview.'
    fritz_token = credentials['preview_fritz_token']
    allocation = credentials['preview_allocation']
else:
    mode = ''
    fritz_token = credentials['fritz_token']
    allocation = credentials['allocation']


# look at any pending observations and determine whether we were successful in observing
retry = parse_pending_observation(credentials, fritz_token, mode, testing)
print(f'retry: {retry}')

# check if it is time for any follow-up triggers
followup = trigger_on_cadence()
print(f'followup: {followup}')

# handle follow-up triggers both for those in the scheduled cadence and for those that were unsuccessful
new_triggers = followup + retry

if new_triggers:
    for x in new_triggers:
        #request new plan and submit if good
        try:
            retrigger_type, superevent_id, gcnevent_id, localization_id, dateobs = x[0], x[1], int(x[2]), int(x[3]), x[4]
            # submit a plan request
            queuename = submit_plan(fritz_token, allocation, superevent_id, gcnevent_id, localization_id, mode)

            # retrieve observation plan for event from Fritz
            time.sleep(15)
            end_time = time.time() + 300  
            fritz_event_status = None
            while fritz_event_status is None and time.time() < end_time:
                fritz_event_status = get_plan_stats(gcnevent_id, queuename, fritz_token, mode)
                time.sleep(30)
            if fritz_event_status is None: 
                raise MyException(f'Could not find an observing plan for {superevent_id}') 

            # check plan stats
            total_time = fritz_event_status[1]
            probability = fritz_event_status[2]
            start_observation = fritz_event_status[3]
            observation_plan_request_id = fritz_event_status[4]

            print(f'Plan for {superevent_id} has {total_time} seconds and {probability} probability - should trigger ZTF')

            if testing:
                raise MyException(f'Dont actually trigger {superevent_id} in testing mode') 

            if total_time > 5400 or probability < 0.5:
                log_value = f"({observation_plan_request_id},{start_observation})"
                update_trigger_log(superevent_id, 'unsuccessful_observation', log_value, append_string=True)
                raise MyException(f'Followup plan for {superevent_id} with {total_time} seconds and {probability} probability does not meet criteria') 
    
            # send plan to ZTF queue
            print(f'ZTF Triggered for {superevent_id}')
            time.sleep(60) # in case i want to double check is looks correct
            trigger_ztf(observation_plan_request_id, fritz_token, mode)
            log_value = f"({observation_plan_request_id},{start_observation})"
            update_trigger_log(superevent_id, 'pending_observation', log_value, append_string=True)
            #email
            if retrigger_type == 'followup':
                message = f'ZTF Triggered for a scheduled follow-up observation of {superevent_id}'
            else:
                message = f'Sending another trigger for tonight after unsuccessful observation of {superevent_id}'
            print(message)
            send_trigger_email(credentials, message, dateobs)
        
        except MyException as e:
            print(e)
            continue
