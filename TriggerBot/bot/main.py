from gcn_kafka import Consumer
import yaml
import time
import pickle
import threading
from TriggerBot.bot.trigger_utils import *
from log import log, heartbeat

with open('../credentials.yaml', 'r') as file:
    credentials = yaml.safe_load(file)
testing = credentials['testing']

log(f'Starting TriggerBot with testing = {testing}')

#choose whether we use preview.fritz or fritz api
if testing:
    mode = 'preview.'
    fritz_token = credentials['preview_fritz_token']
    allocation = credentials['preview_allocation']
else:
    mode = ''
    fritz_token = credentials['fritz_token']
    allocation = credentials['allocation']

MLP = pickle.load(open('mlp_model.sav', 'rb'))

config = {'group.id': 'ztfmasstrigger',
          'auto.offset.reset': 'earliest',
          'enable.auto.commit': False,
          'max.poll.interval.ms': 600050}

consumer = Consumer(config=config,
                    client_id=credentials['client_id'],
                    client_secret=credentials['client_secret'],
                    domain='gcn.nasa.gov')

consumer.subscribe(['gcn.classic.voevent.LVC_PRELIMINARY',
                    'gcn.classic.voevent.LVC_INITIAL',
                    'gcn.classic.voevent.LVC_UPDATE'])

log('subscribed to Kafka consumer')
heartbeat_thread = threading.Thread(target=heartbeat)
heartbeat_thread.daemon = True
heartbeat_thread.start()

while True:
    try:
        for message in consumer.consume(timeout=1.0):
            if message.value() is None:
                continue
            try:
                value = message.value()
                parsed = parse_gcn_dict(value)
                params = get_params(parsed)
                dateobs = params[0]
                mjd = params[1]
                superevent_id = params[2]
                significant = params[3]
                alert_type = params[4]
                group = params[5]
                prob_bbh = params[6]
                prob_ter = params[7]
                far = params[8]
                distmean = params[9]
                a90 = params[10]
                skymap_name = params[11]

                # open triggered_events.csv and check for superevent_id
                triggered, trigger_plan_id = check_triggered_csv(superevent_id)

                if (
                    superevent_id[0] != 'S' or
                    alert_type == 'RETRACTION' or
                    significant != '1'or 
                    group != 'CBC' or 
                    prob_bbh < 0.5 or
                    prob_ter > 0.4 or
                    distmean == 'error' or
                    far < 10 or 
                    a90 > 1000 or
                    (alert_type == 'Preliminary' and skymap_name[-1] == 0)
                ):
                    if triggered:
                        update_trigger_log(superevent_id, 'valid', False)
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                        log(f'{superevent_id} has trigger but no longer is valid')
                    
                    logmessage = f'{superevent_id} did not pass initial criteria'
                    log(logmessage)
                    raise MyException(logmessage)

                log(f'Processing {superevent_id} from {alert_type} alert')

                mass = m_total_mlp(MLP, distmean, far, dl_bns=168.)
                if mass < 60:
                    if triggered:
                        update_trigger_log(superevent_id, 'valid', False)
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                    logmessage = f'{superevent_id} did not pass mass criteria'
                    log(logmessage)
                    raise MyException(logmessage)
                
                log(f'{superevent_id} passed mass criteria')
                
                # find gcn event on fritz 
                if not testing:
                    time.sleep(30)
                end_time = time.time() + 300
                if testing:
                    end_time = time.time() + 1  
                gcnevent_id = None
                while gcnevent_id is None and time.time() < end_time:
                    gcnevent_id, localization_id = query_fritz_gcn_events(dateobs, skymap_name, fritz_token, mode)
                    time.sleep(30)
                if gcnevent_id is None:
                    logmessage=f'Could not find a GCN event on Fritz for {superevent_id}'
                    log(logmessage)
                    raise MyException(logmessage)
                
                # submit plan request to Fritz
                log(f'Submitting plan request for {superevent_id}')
                queuename = submit_plan(fritz_token, allocation, superevent_id, gcnevent_id, localization_id, mode)
                            
                # retrieve observation plan for event from Fritz
                time.sleep(15)
                end_time = time.time() + 300  
                fritz_event_status = None
                while fritz_event_status is None and time.time() < end_time:
                    fritz_event_status = get_plan_stats(gcnevent_id, queuename, fritz_token, mode)
                    time.sleep(30)
                if fritz_event_status is None: 
                    logmessage = f'Could not find an observing plan for {superevent_id}'
                    log(logmessage)
                    raise MyException(logmessage)
                
                #API call to Kowalski - check for event keywords in ZTF observing queue
                if not testing:
                    keyword_list = [dateobs, superevent_id, gcnevent_id]    
                    kowalski_event_status = query_kowalski_ztf_queue(keyword_list, fritz_token, allocation)
                    log(f'checked ZTF observing queue for key words related to {superevent_id}')
                else:
                    kowalski_event_status = False
                
                #have we triggered on the event
                if fritz_event_status[0] or kowalski_event_status:
                    previous_trigger = True
                else:
                    previous_trigger = False
                    
                total_time = fritz_event_status[1]
                probability = fritz_event_status[2]
                start_observation = fritz_event_status[3]
                observation_plan_request_id = fritz_event_status[4]

                if total_time > 5400 or probability < 0.5:
                    if triggered:
                        update_trigger_log(superevent_id, 'valid', False)
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                    logmessage = f'Followup plan for {superevent_id} with {total_time} seconds and {probability} probability does not meet criteria'
                    log(logmessage)
                    raise MyException(logmessage)
                            
                if Time.now().mjd - mjd > 1:
                    # don't trigger on events older than 1 day
                    logmessage = f'{superevent_id} is more than 1 day old'
                    log(logmessage)
                    raise MyException(logmessage)

                if previous_trigger:
                    logmessage = f'Previous trigger for {superevent_id}'
                    log(logmessage)
                    raise MyException(logmessage)
                
                if triggered:
                    if not check_before_sunset():
                        logmessage = f'Too late to update submitted trigger for {superevent_id}'
                        log(logmessage)
                        raise MyException(logmessage)
                    else:
                        # remove current submitted plan so we can submit new one
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                        logmessage = f'Removing previous trigger for {superevent_id} so we can resubmit updated plan'
                        log(logmessage)
                        raise MyException(logmessage)

                if testing:
                    logmessage=f'Plan for {superevent_id} has {total_time} seconds and {probability} probability - but dont trigger in testing mode'
                    log(logmessage)
                    raise MyException(logmessage)

                # check if ZTF survey naturaly covered the skymap previous nights
                #NEED TO UPDATE THIS FUNCTION SO IT CHECKS NOT JUST FOR OBSERVATIONS BUT FOR SUFFICIENT % COVERAGE
                startdate = (Time(dateobs) - TimeDelta(2, format='jd')).iso
                observations = check_executed_observation(startdate, dateobs, gcnevent_id, fritz_token, mode)
                if observations['data']['totalMatches'] >= 1:
                    logmessage=f'There is recent coverage of {superevent_id} - not triggering'
                    log(logmessage)
                    raise MyException(logmessage)

                # send plan to ZTF queue
                trigger_ztf(observation_plan_request_id, fritz_token, mode)
                log(f'Triggered ZTF for {superevent_id} at {Time.now()}')
                
                #write to triggered_events.csv
                trigger_cadence = generate_cadence_dates(dateobs)
                gcn_type = (alert_type, skymap_name)
                queued_plan = (observation_plan_request_id, start_observation)
                valid = True
                add_triggercsv(superevent_id, dateobs, gcn_type, gcnevent_id, localization_id, queued_plan, trigger_cadence, valid)         
                message = f'ZTF Triggered for {superevent_id}'
                send_trigger_email(credentials, message, dateobs)

                log(f'post-trigger sleep')
                time.sleep(120) # after triggering pause to avoid double triggers on quickly updated gcn
        
            
            except MyException as e:
                log(e)
                continue

            finally:
                consumer.commit(message)

    except Exception as e:
        log(e)
        continue




        