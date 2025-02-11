from gcn_kafka import Consumer
import yaml
import time
import pickle
from triggerfunctions import *

with open('../credentials.yaml', 'r') as file:
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

while True:
    try:
        for message in consumer.consume():
            if message is None:
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
                    raise MyException(f'{superevent_id} did not pass initial criteria') 

                print(f'Processing {superevent_id}')

                mass = m_total_mlp(MLP, distmean, far, dl_bns=168.)
                if mass < 60:
                    if triggered:
                        update_trigger_log(superevent_id, 'valid', False)
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                    raise MyException(f'{superevent_id} did not pass mass criteria') 
                
                print(f'{superevent_id} passed mass criteria')
                
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
                    raise MyException(f'Could not find a GCN event on Fritz for {superevent_id}')
                
                # submit plan request to Fritz
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
                
                #API call to Kowalski - check for event keywords in ZTF observing queue
                if not testing:
                    keyword_list = [dateobs, superevent_id, gcnevent_id]    
                    kowalski_event_status = query_kowalski_ztf_queue(keyword_list, fritz_token, allocation)
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
                observation_plan_id = fritz_event_status[4]

                if total_time > 5400 or probability < 0.5:
                    if triggered:
                        update_trigger_log(superevent_id, 'valid', False)
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                    raise MyException(f'Plan for {superevent_id} with {total_time} seconds and {probability} probability does not meet criteria') 
                            
                if Time.now().mjd - mjd > 1:
                    # don't trigger on events older than 1 day
                    raise MyException(f'{superevent_id} is more than 1 day old') 

                if previous_trigger:
                    raise MyException(f'Another group triggered on {superevent_id}') 
                
                if triggered:
                    if not check_before_sunset():
                        raise MyException(f'Too late to update submitted trigger for {superevent_id}') 
                    else:
                        # remove current submitted plan so we can submit new one
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)

                if testing:
                    print(f'Plan for {superevent_id} has {total_time} seconds and {probability} probability - would trigger ZTF')
                    raise MyException(f'Dont actually trigger {superevent_id} in testing mode') 

                # check if ZTF survey naturaly covered the skymap previous nights
                #NEED TO UPDATE THIS FUNCTION SO IT CHECKS NOT JUST FOR OBSERVATIONS BUT FOR SUFFICIENT % COVERAGE
                startdate = (Time(dateobs) - TimeDelta(2, format='jd')).iso
                observations = check_executed_observation(startdate, dateobs, gcnevent_id, fritz_token, mode)
                if observations['data']['totalMatches'] >= 1:
                    print(f'There is recent coverage of {superevent_id} - not triggering')  
                    raise MyException(f'{superevent_id} has recent coverage')

                # send plan to ZTF queue
                trigger_ztf(observation_plan_id, fritz_token, mode)
                
                #write to triggered_events.csv
                trigger_cadence = generate_cadence_dates(dateobs)
                gcn_type = (alert_type, skymap_name)
                queued_plan = (observation_plan_id, start_observation)
                valid = True
                add_triggercsv(superevent_id, dateobs, gcn_type, gcnevent_id, localization_id, queued_plan, trigger_cadence, valid)         
                message = f'ZTF Triggered for {superevent_id}'
                send_trigger_email(credentials, message, dateobs)

                time.sleep(120) # after triggering pause to avoid double triggers on quickly updated gcn
        
            
            except MyException as e:
                print(e)
                continue
            
            except Exception as e:
                print(e)
                continue

            finally:
                consumer.commit(message)

    except Exception as e:
        print(e)
        continue




        