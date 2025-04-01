import numpy as np
import pandas as pd
from astropy.cosmology import Planck15 as cosmo
import astropy.cosmology as cos
from astropy.table import Table
import astropy.units as u
import astropy_healpix as ah
from astropy.time import Time, TimeDelta
from astropy.coordinates import EarthLocation
from astroplan import Observer
import datetime
from datetime import timedelta
import requests
from io import BytesIO
import json
import xmltodict
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from sklearn.neural_network import MLPRegressor

class MyException(Exception):
    pass


"""
Processing the GCN
"""

def parse_gcn_dict(response):
    dict=xmltodict.parse(response)
    return (dict)

def get_a(skymap,probarea):
    skymap.sort('PROBDENSITY', reverse = True)
    level, ipix = ah.uniq_to_level_ipix(skymap['UNIQ'])
    pixel_area = ah.nside_to_pixel_area(ah.level_to_nside(level))
    prob = pixel_area * skymap['PROBDENSITY']
    cumprob = np.cumsum(prob)
    i = cumprob.searchsorted(probarea)
    area = (pixel_area[:i].sum()).to_value(u.deg ** 2)
    return (area)

def get_params(dict):
    try:
        event_id  = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'GraceID'][0]
    except:
        raise MyException(f'error getting params: could not parse graceid') 
    try:
        t0 = dict['voe:VOEvent']['WhereWhen']['ObsDataLocation']['ObservationLocation']['AstroCoords']['Time']['TimeInstant']['ISOTime']
        # mimicking skysurvey time conversions to ensure rounding is the same
        dateobs = Time(t0,precision=0)
        dateobs = Time(dateobs.iso).datetime
        dateobs_str = dateobs.strftime('%Y-%m-%dT%H:%M:%S')
        mjd = round(Time(t0).mjd) 
        alert_type = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'AlertType'][0]
        group = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'Group'][0]
        significant  = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'Significant'][0]
        classification = [item for item in dict['voe:VOEvent']['What']['Group'] if item.get('@name') == 'Classification']
        try:
            prob_bbh = float([item['@value'] for item in classification[0]['Param'] if item.get('@name') == 'BBH'][0])  
        except:
            prob_bbh = 0
        try:
            prob_ter = float([item['@value'] for item in classification[0]['Param'] if item.get('@name') == 'Terrestrial'][0])
        except:
            prob_ter = 1
        far = float(dict['voe:VOEvent']['What']['Param'][9]['@value'])
        skymap_url = [item['Param']['@value'] for item in dict['voe:VOEvent']['What']['Group'] if item.get('@name') == 'GW_SKYMAP'][0]
        skymap_response = requests.get(skymap_url)
        skymap_bytes = skymap_response.content
        skymap = Table.read(BytesIO(skymap_bytes))
        try:
            distmean = skymap.meta['DISTMEAN']
        except:
            distmean = 'error'
        far_format = 1. / (far * 3.15576e7) 
        a90 = round(get_a(skymap,0.9))
        skymap_url = [item['Param']['@value'] for item in dict['voe:VOEvent']['What']['Group'] if item.get('@name') == 'GW_SKYMAP'][0]
        skymap_type = skymap_url.split('files/')[1] 
        return dateobs_str, mjd, event_id, significant, alert_type, group, prob_bbh, prob_ter, far_format, distmean, a90, skymap_type
    except:
        raise MyException(f'error getting params for {event_id}')
    
def m_total_mlp(MLP_model, dl_bbh, far, dl_bns = 168.):
    z = cos.z_at_value(cosmo.luminosity_distance, dl_bbh * u.Mpc, method = 'bounded')
    X = np.array([np.log10(dl_bbh / dl_bns), np.log10(1 + z), np.log10(far)])
    X = X.reshape(1, -1)
    mass = MLP_model.predict(X)[0]
    return 10. ** mass





"""
fritz queries
"""
        
def query_fritz_gcn_events(dateobs_id, local_name, token, mode):
    try:
        headers = {'Authorization': f'token {token}'}
        endpoint = f'https://{mode}fritz.science/api/gcn_event/{dateobs_id}'
        response = requests.request('GET', endpoint, headers=headers)
        if response.status_code == 200: 
            json_string = response.content.decode('utf-8')
            json_data = json.loads(json_string)
            gcnevent_id = json_data['data']['id']
            localization_id = [x['id'] for x in json_data['data']['localizations'] if x['localization_name'] == local_name]
            if len(localization_id) == 0:
                raise MyException(f'Couldnt find the data for {dateobs_id}, {local_name}')
            return gcnevent_id, localization_id[0]
    except Exception as e:
        print(f'error: {e}')
        return None


def compute_plan_start_end():
    location = EarthLocation(lat=33.3564, lon=-116.865, height=1712) #Palomar
    observer = Observer(location=location, timezone='US/Pacific')

    now = Time.now()
    sunset_time = observer.sun_set_time(now, which='next')
    sunrise_time = observer.sun_rise_time(now, which='next')
    if sunrise_time < sunset_time:
        startdate = now
    else:
        startdate = sunset_time
    # necessary? to be safe go an hour before sunset
    startdate_return = (startdate - TimeDelta(1*3600, format='sec')).utc.iso
    enddate_return = (startdate + TimeDelta(1*3600*15, format='sec')).utc.iso
    return startdate_return, enddate_return

def check_before_sunset():
    location = EarthLocation(lat=33, lon=-116, height=1712) #Palomar
    observer = Observer(location=location, timezone='US/Pacific')
    now = Time.now()
    sunset_time = observer.sun_set_time(now, which='next')
    sunrise_time = observer.sun_rise_time(now, which='next')
    if sunrise_time < sunset_time:
        before_sunset = False
    else:
        before_sunset = True
    return before_sunset

def submit_plan(token, allocation_id, gracedbid, gcnevent_id, localization_id, mode):
    startdate, enddate = compute_plan_start_end()
    queuename= f'{gracedbid}_BBHBot_{startdate}'

    # field reference data is not loaded to preview instance of Fritz
    if mode == 'preview.':
        ref=False
    else:
        ref=True

    url = f'https://{mode}fritz.science/api/observation_plan'
    data = {
            "gcnevent_id": gcnevent_id,
            "allocation_id": allocation_id,
            "localization_id": localization_id,
            "payload": {
                "filters": "ztfg,ztfr",
                "end_date": enddate,
                "ra_slice": False,
                "max_tiles": False,
                "program_id": "Caltech",
                "queue_name": queuename,
                "start_date": startdate,
                "use_primary": True,
                "exposure_time": 30,
                "schedule_type": "greedy",
                "use_secondary": False,
                "galactic_plane": False,
                "use_references": ref,
                "filter_strategy": "block",
                "maximum_airmass": 2,
                "subprogram_name": "GW",
                "balance_exposure": True,
                "schedule_strategy": "tiling",
                "integrated_probability": 90
            }
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f'token {token}'
    }
    response = requests.post(url, json=data, headers=headers)
    return queuename

def get_plan_stats(gcnevent_id, queuename, token, mode):
    try:
        headers = {'Authorization': f'token {token}'}
        endpoint = f'https://{mode}fritz.science/api/gcn_event/{gcnevent_id}/observation_plan_requests'
        response = requests.request('GET', endpoint, headers=headers)
        if response.status_code == 200: 
            json_string = response.content.decode('utf-8')
            json_data = json.loads(json_string)

        if len(json_data['data']) == 0:
            raise MyException(f'No requests found for {gcnevent_id}')
        
        # check if already submitted to queue
        status = [x['status'] for x in json_data['data']]
        if 'submitted to telescope queue' in status:
            past_submission = True
            print('Already submitted to queue')
        else:
            past_submission = False

        generated_plan = [x for x in json_data['data'] if x['payload']['queue_name'] == queuename]
        if len(generated_plan) == 0:
            raise MyException(f'No generated plan for {gcnevent_id}')
        observation_plans = generated_plan[0]['observation_plans']
        if len(observation_plans) == 0:
            raise MyException(f'No observation plans for {gcnevent_id}')
        elif len(observation_plans) > 1:
            raise MyException(f'Multiple observation plans for {gcnevent_id}')

        stats = observation_plans[0]['statistics']
        # make sure there is one entry for observing plan here
        if len(stats) > 1:
            raise MyException(f'Multiple statistics found for {gcnevent_id}')
        elif len(stats) == 0:
            raise MyException(f'No statistics found for {gcnevent_id}')

        stats = observation_plans[0]['statistics']
        total_time = stats[0]['statistics']['total_time']
        probability = stats[0]['statistics']['probability']
        start_observation = stats[0]['statistics']['start_observation']
        observation_plan_id = stats[0]['observation_plan_id']
        print(f'Total time: {total_time}, probability: {probability}')
        return past_submission, total_time, probability, start_observation, observation_plan_id

    except MyException as e:
        print(f'error: {e}')
        return None

# kowalski api call to check current observing queue
def query_kowalski_ztf_queue(keywords, token, allocation):
    """
    check current items in the ZTF observing queue and wordsearch for keywords from our event
    """
    headers = {'Authorization': f'token {token}'}
    endpoint = f'https://fritz.science/api/observation/external_api/{allocation}?queuesOnly=true'
    response = requests.request('GET', endpoint, headers=headers)
    if response.status_code != 200:   
        raise Exception(f'API call to ZTF queue failed')         
    json_string = response.content.decode('utf-8')
    json_data = json.loads(json_string)
    queue_names = json_data['data']['queue_names']
    for name in queue_names:
        for keyword in keywords:
            if keyword in name:
                return 'Already Submitted'
    return None


def trigger_ztf(plan_request_id, token, mode):
    """
    trigger ztf on a plan request
    """
    headers = {'Authorization': f'token {token}'}
    endpoint = f'https://{mode}fritz.science/api/observation_plan/{plan_request_id}/queue'
    response = requests.request('POST', endpoint, headers=headers)
    if response.status_code != 200: 
        raise MyException(f'Could not trigger - {response.status_code} - {response.text}')
    
def delete_trigger_ztf(plan_request_id, token, mode):
    """
    delete a triggered plan request
    """
    headers = {'Authorization': f'token {token}'}
    endpoint = f'https://{mode}fritz.science/api/observation_plan/{plan_request_id}/queue'
    response = requests.request('DELETE', endpoint, headers=headers)
    if response.status_code != 200: 
        raise MyException(f'Could not trigger - {response.status_code} - {response.text}')


#### Note - probably need to improve this
def check_executed_observation(startdate, enddate, gcnid, token, mode):
    """
    verify that we observed the event
    """

    url = f'https://{mode}fritz.science/api/observation'
    data = {
            "startDate":startdate,
            "endDate":enddate,
            # "localizationDateobs": dateobs,
            "instrumentName":"ZTF",
            "localizationName": gcnid,
            "localizationCumprob": 0.9,
            # "returnStatistics": True
            }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f'token {token}'
    }
    response = requests.request('GET', url, params=data, headers=headers)
    return response.json()


"""
Bookkeeping
"""

def generate_cadence_dates(date):
    cadence = [7, 14, 21, 28, 40, 50]
    input_date = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S')
    date_only = datetime.datetime(input_date.year, input_date.month, input_date.day)
    new_dates = [(date_only + timedelta(days=days)).strftime('%Y-%m-%d') for days in cadence]
    return new_dates

def check_triggered_csv(superevent_id):
    df = pd.read_csv('./data/triggered_events.csv')
    triggered = superevent_id in df['superevent_id'].values
    if triggered:
        trigger_plan_id = df[df['superevent_id'] == superevent_id]['observation_plan_id'].values[0]
    else:
        trigger_plan_id = None
    return triggered, trigger_plan_id

def update_trigger_log(superevent_id_to_check, column, value):
    df = pd.read_csv('./data/triggered_events.csv')
    df.loc[df['superevent_id'] == superevent_id_to_check, column] = value
    df.to_csv('./data/triggered_events.csv', index=False)

def add_triggercsv(superevent_id, dateobs, gcn_type, gcnid, localizationid, queued_plan, trigger_cadence, valid):
    # Create a DataFrame with the new event data
    new_event = pd.DataFrame([{
        'superevent_id': superevent_id,
        'dateobs': dateobs,
        'gcn_type': gcn_type,
        'gcn_id': gcnid,
        'localization_id': localizationid,
        'trigger_cadence': str(trigger_cadence),
        'pending_observation': queued_plan,
        'unsuccessful_observation': None,
        'successful_observation': None,
        'valid': valid
    }])

    # Append the new event to the existing CSV file
    new_event.to_csv('./data/triggered_events.csv', mode='a', header=False, index=False)


def send_email(sender_email, sender_password, recipient_emails, subject, body):
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587

    try:
        # Connect to the SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)

        # Send the email to each recipient
        for recipient in recipient_emails:
            # Create the email
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'html'))  # Send as HTML

            server.sendmail(sender_email, recipient, msg.as_string())

        print("Emails sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")
    finally:
        # Close the SMTP server connection
        server.quit()

def send_trigger_email(credentials, subject_message, dateobs):
    sender_email = credentials['sender_email']
    sender_password = credentials['sender_password']
    recipient_emails = credentials['recipient_emails']
    subject = subject_message
    fritz_url = f'https://fritz.science/gcn_events/{dateobs}'
    body = f'<html><body><p>{fritz_url}</p></body></html>'
    send_email(sender_email, sender_password, recipient_emails, subject, body)
