from cadencefunctions import *
from triggerfunctions import *
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

#open log of triggers
trigger_log = pd.read_csv(
    './data/triggered_events.csv', 
    dtype={
        "gcn_id": "Int64",
        "localization_id": "Int64"
    }
)

# look at any pending observations and determine whether we were successful in observing
retry = parse_pending_observation(trigger_log, credentials, fritz_token, mode, testing)

# check if it is time for any follow-up triggers
followup = trigger_on_cadence(trigger_log)

# handle follow-up triggers both for those in the scheduled cadence and for those that were unsuccessful
new_triggers = followup + retry
print(f'New triggers: {new_triggers}')
if new_triggers:
    for x in new_triggers:
        #request new plan and submit if good
        try:
            retrigger_type, superevent_id, gcnevent_id, localization_id, dateobs = x[0], x[1], x[2], x[3], x[4]
            # submit a plan request
            print(f'requested plan for {superevent_id}')

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
            observation_plan_id = fritz_event_status[4]

            if testing:
                print(f'Plan for {superevent_id} has {total_time} seconds and {probability} probability - would trigger ZTF')
                raise MyException(f'Dont actually trigger {superevent_id} in testing mode') 

            if total_time > 5400 or probability < 0.5:
                update_trigger_log(superevent_id, 'unsuccessful_observation', (observation_plan_id, start_observation))
                raise MyException(f'Followup plan for {superevent_id} with {total_time} seconds and {probability} probability does not meet criteria') 
            
            print('made it to trigger')

            # # send plan to ZTF queue
            # trigger_ztf(observation_plan_id, fritz_token, mode)
            # update_trigger_log(superevent_id, 'pending_observation', (observation_plan_id, start_observation))
            # #email
            # if retrigger_type == 'followup':
            #     message = f'ZTF Triggered for a scheduled follow-up observation of {superevent_id}'
            # else:
            #     message = f'Sending another trigger for tonight after unsuccessful observation of {superevent_id}'
            # send_trigger_email(credentials, message, dateobs)
        
        except MyException as e:
            print(e)
            continue
