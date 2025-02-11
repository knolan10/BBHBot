import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from astropy.table import Table
import astropy.cosmology as cos
from astropy.cosmology import Planck15 as cosmo
import astropy_healpix as ah
import astropy.units as u
from astropy.time import Time
from datetime import datetime, timedelta
import requests
import re
from io import BytesIO
import xmltodict
import pickle
import gzip
import base64
import json
import glob
from bs4 import BeautifulSoup
import os
import io
from io import StringIO
from io import BytesIO
import yaml
from ligo.gracedb.rest import GraceDb
import argsparse
g = GraceDb()

with open('../credentials.yaml', 'r') as file:
    credentials = yaml.safe_load(file)
github_token = credentials['github_token']
kowalski_token = credentials['kowalski_token']
kowalski_password = credentials['kowalski_password']
fritz_token = credentials['fritz_token']    
allocation = credentials['allocation']    

class Gracedb:
    # cut unused params returned

    """
    get new events that haven't been processed yet
    use get_new_events to return : 
    superevent_id, event_page, alert_type, instrument, pipeline, group, significant, prob_bbh, prob_ter, 
    far_format, skymap_url, date, fritz_dateid, distmean, diststd, dateobs_str, a90, a50, skymap_str, zmin,
    zmax, skymap, mass
    """
    def get_gcn_urls(self, ids, files):
        superevent_files = [i['links']['files'] for i in files]
        event_files = [g.files(graceid).json() for graceid in ids]
        file = [
            'none' if any('etraction' in s for s in list(files))
            else id+'-5-Update.xml,0' if id+'-5-Update.xml,0' in list(files)
            else id+'-5-Update.xml' if id+'-5-Update.xml' in list(files)
            else id+'-4-Update.xml,0' if id+'-4-Update.xml,0' in list(files)
            else id+'-4-Update.xml' if id+'-4-Update.xml' in list(files)
            else id+'-3-Update.xml,0' if id+'-3-Update.xml,0' in list(files)
            else id+'-2-Update.xml,0' if id+'-2-Update.xml,0' in list(files)
            else id+'-4-Initial.xml,0' if id+'-4-Initial.xml,0' in list(files)
            else id+'-3-Initial.xml,0' if id+'-3-Initial.xml,0' in list(files)
            else id+'-2-Initial.xml,0' if id+'-2-Initial.xml,0' in list(files)
            else id+'-2-Preliminary.xml,0' if id+'-2-Preliminary.xml,0' in list(files)
            else 'none'
            for files, id in zip(event_files, ids)
        ]
        urls = [i + j for i, j in zip(superevent_files, file)]
        [print(x) for x in urls if "none" in x]
        urls_save = [x for x in urls if "none" not in x]
        return urls_save

    def get_params(self, xml_urls):
        try:
            response = requests.get(xml_urls)
            dict = xmltodict.parse(response.text)
            superevent_id = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'GraceID'][0]
            event_page = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'EventPage'][0]
            alert_type = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'AlertType'][0]
            instrument = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'Instruments'][0]
            pipeline = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'Pipeline'][0]
            group = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'Group'][0]
            significant = [item['@value'] for item in dict['voe:VOEvent']['What']['Param'] if item.get('@name') == 'Significant'][0]
            classification = [item for item in dict['voe:VOEvent']['What']['Group'] if item.get('@name') == 'Classification']
            prob_bbh = float([item['@value'] for item in classification[0]['Param'] if item.get('@name') == 'BBH'][0])
            prob_ter = float([item['@value'] for item in classification[0]['Param'] if item.get('@name') == 'Terrestrial'][0])
            far = float(dict['voe:VOEvent']['What']['Param'][9]['@value'])
            far_format = 1. / (far * 3.15576e7)
            skymap_url = [item['Param']['@value'] for item in dict['voe:VOEvent']['What']['Group'] if item.get('@name') == 'GW_SKYMAP'][0]
            date = dict['voe:VOEvent']['Who']['Date']
            t0 = dict['voe:VOEvent']['WhereWhen']['ObsDataLocation']['ObservationLocation']['AstroCoords']['Time']['TimeInstant']['ISOTime']
            dateobs = Time(t0, precision=0)
            dateobs = Time(dateobs.iso).datetime
            fritz_dateid = dateobs.strftime('%Y-%m-%dT%H:%M:%S')
            params = [superevent_id, event_page, alert_type, instrument, pipeline, group, significant, prob_bbh, prob_ter, far_format, skymap_url, date, fritz_dateid]
            return params
        except:
            print(f'error loading xml: {xml_urls}')

    def proc_skymap(self, skymap_url):
        skymap_response = requests.get(skymap_url)
        skymap_bytes = skymap_response.content
        skymap = Table.read(BytesIO(skymap_bytes))
        skymap_str = base64.b64encode(skymap_bytes).decode('utf-8')
        return skymap, skymap_str

    def get_a(self, skymap, probarea):
        skymap.sort('PROBDENSITY', reverse=True)
        level, ipix = ah.uniq_to_level_ipix(skymap['UNIQ'])
        pixel_area = ah.nside_to_pixel_area(ah.level_to_nside(level))
        prob = pixel_area * skymap['PROBDENSITY']
        cumprob = np.cumsum(prob)
        i = cumprob.searchsorted(probarea)
        area = (pixel_area[:i].sum()).to_value(u.deg ** 2)
        return area

    def extract_skymap_params(self, skymap_url):
        skymap, skymap_str = self.proc_skymap(skymap_url)
        try:
            distmean = skymap.meta['DISTMEAN']
            diststd = skymap.meta['DISTSTD']
            t0 = skymap.meta['DATE-OBS']
            dateobs = Time(t0, precision=0)
            dateobs = Time(dateobs.iso).datetime
            dateobs_str = dateobs.strftime('%Y-%m-%dT%H:%M:%S')
            a90 = self.get_a(skymap, 0.9)
            a50 = self.get_a(skymap, 0.5)
            if distmean - 3 * diststd > 0:
                zmin = cos.z_at_value(cosmo.luminosity_distance, (distmean - 3 * diststd) * u.Mpc, method='bounded').value
            else:
                zmin = 0
            zmax = cos.z_at_value(cosmo.luminosity_distance, (distmean + 3 * diststd) * u.Mpc, method='bounded').value
            return [distmean, diststd, dateobs_str, a90, a50, skymap_str, zmin, zmax, skymap]
        except:
            print(f'error loading skymap {skymap_url}')
            return ['None']
        
    def m_total_mlp(self, MLP_model, dl_bbh, far, dl_bns=168.):
        z = cos.z_at_value(cosmo.luminosity_distance, dl_bbh * u.Mpc, method='bounded')
        X = np.array([np.log10(dl_bbh / dl_bns), np.log10(1 + z), np.log10(far)])
        X = X.reshape(1, -1)
        mass = MLP_model.predict(X)[0]
        return 10. ** mass

    def get_new_events(self):
        event_iterator = g.superevents('runid: O4b SIGNIF_LOCKED')
        graceids_all = [superevent['superevent_id'] for superevent in event_iterator]
        print(len(graceids_all), 'significant superevents in O4b')
        responses = [g.superevent(id) for id in graceids_all]
        data_all = [r.json() for r in responses]
        with open('dicts/events_dict_O4b.json', 'r') as file:
            events_dict_add = json.load(file)
        new_events = [(i, j) for i, j in zip(graceids_all, data_all) if i not in list(events_dict_add.keys())]
        graceids = [x[0] for x in new_events]
        data = [x[1] for x in new_events]
        gcn_urls = self.get_gcn_urls(graceids, data)
        gcn_params = [self.get_params(url) for url in gcn_urls]
        low_prob_bbh = [x for x in gcn_params if x[7] < 0.5 or x[8] > 0.3]
        params = [x for x in gcn_params if x[7] > 0.5 and x[8] < 0.3]
        print(f'{len(params)} events')
        skymap_urls = [x[10] for x in params]
        skymap_data = [self.extract_skymap_params(url) for url in skymap_urls]
        # mass
        dist = [x[0] for x in skymap_data]
        far = [x[9] for x in params]
        modelpath = '../trigger/mlp_model.sav'
        MLP = pickle.load(open(modelpath, 'rb'))
        mass = [self.m_total_mlp(MLP, d, f, dl_bns=168.) for d, f in zip(dist, far)]
        return params + skymap_data + mass

class Fritz():
    def __init__(self, eventid, dateid, a90, far, mass):
        self.eventid = eventid
        self.dateid = dateid
        self.a90 = a90
        self.far = far
        self.mass = mass    

    def query_fritz_observation_plans(allocation_id, token):
        headers = {'Authorization': f'token {token}'}
        endpoint = f'https://fritz.science/api/allocation/observation_plans/{allocation_id}?numPerPage=1000'
        response = requests.request('GET', endpoint, headers=headers)
        if response.status_code == 200:
            json_string = response.content.decode('utf-8')
            json_data = json.loads(json_string)            
            return json_data
        else:
            print(response.status_code)
            return None
        
    # get the statistics for a potential observation plan
    def determine_trigger_status(observation_plans, eventid, dateid, a90, far, mass):
        matching_requests = [x for x in observation_plans if x['localization']['dateobs'] == dateid]
        #handling events without plan requests
        if len(matching_requests) == 0:
            if datetime.fromisoformat(dateid) < datetime.fromisoformat('2024-09-14T00:00:00'):
                print(f'{eventid} predates trigger')
                return ["correct", 'predates trigger']
            else:
                if far < 10 or a90 > 1000 or mass < 60:
                    print(f'Event doesnt pass criteria - correct no plan request for {eventid}')
                    return ["correct", "not triggered"]
                else:
                    print(f'Error: should have requested plan for {eventid}')
                    trigger_status = "missed plan request"
                    return ['error', 'missed plan request']
        # now only considering events that have a plan request
        else:
            # check whether we triggered
            status = [x['status'] for x in matching_requests]
            if 'submitted to telescope queue' in status:
                trigger_status = "triggered"
            else:
                trigger_status = "not triggered"

            # stop considering events that predate the trigger
            if datetime.fromisoformat(dateid) < datetime.fromisoformat('2024-09-14T00:00:00'):
                if trigger_status == 'triggered':
                    print(f'{eventid} trigger predating automated trigger')
                    return ['correct','non-automated trigger']
                else:
                    print(f'{eventid} predates trigger')
                    return ['correct','predates trigger']
            # now down to events with plans while the trigger is operational
            else:
                # check whether we should have triggered on the event - need to get plan statistics to check this
                # the triggered case
                if trigger_status == "triggered":
                    # look at stats for the submitted plan
                    plans = [x for x in matching_requests if x['status'] == 'submitted to telescope queue']
                    if len(plans) != 1:
                        print(f'Multiple triggers: inspect {eventid}')
                        return ['inspect','multiple triggers']
                # the not triggered case
                else:
                    plans = [x for x in matching_requests if x['observation_plans'][0]['statistics'] and x['observation_plans'][0]['statistics'][0]['statistics']['num_observations'] != 0]
                    if not plans:
                        if far < 10 or a90 > 1000 or mass < 60:
                            print(f'requested plan when we shouldnt have but correctly didnt trigger - parameters dont pass criteria {eventid}')
                            return ['correct',"not triggered"]
                        else:
                            print(f'No valid plans found for {eventid}')
                            return ['error','no valid plan']
                #for non triggered events take the most recent plan as truth, ie if earlier plan passes criteria but later one doesn't go by the later one
                most_recent_plan = max(plans, key=lambda x: x['modified'])
                observation_plan = most_recent_plan['observation_plans']
                stats = observation_plan[0]['statistics']
                total_time = stats[0]['statistics']['total_time'] 
                probability = stats[0]['statistics']['probability'] 
                start = stats[0]['statistics']['start_observation'] 
                # independently get the intended trigger status
                if (far < 10 or
                a90 > 1000 or
                mass < 60 or
                probability < 0.5 or
                total_time > 5400):
                    intended_trigger_status = "not triggered"
                else:
                    intended_trigger_status = "triggered"
                # compare the trigger status to the intended trigger status
                if trigger_status == "triggered" and intended_trigger_status == "triggered":
                    print(f'triggered on {eventid}')
                    return ['correct','triggered', total_time, probability, start]
                elif trigger_status == "triggered" and intended_trigger_status == "not triggered":
                    print(f'Error: bad trigger for {eventid}')
                    return ['error','bad trigger', total_time, probability, start]
                elif trigger_status == "not triggered" and intended_trigger_status == "triggered":
                    print(f'Error: missed trigger for {eventid}')
                    return ['error','missed trigger', total_time, probability, start]
                elif trigger_status == "not triggered" and intended_trigger_status == "not triggered":
                    print(f'not triggered on {eventid}')
                    return ['correct','not triggered', total_time, probability, start]
        
    def save_trigger_details(self):    
        plans = self.query_fritz_observation_plans(allocation, fritz_token)
        observation_plan_requests = plans['data']['observation_plan_requests']
        print(f'There are currently {plans['data']['totalMatches']} observation plans generated')
        trigger_status = [self.determine_trigger_status(observation_plan_requests, i, j, a, f, m) 
                          for i,j,a,f,m in zip(self.eventid, self.dateid, self.a90, self.far, self.mass)]
        error = [(i, x) for i, x in enumerate(trigger_status) if x[0] == 'error']
        correct = [(i, x) for i, x in enumerate(trigger_status) if x[0] == 'correct']
        inspect = [(i, x) for i, x in enumerate(trigger_status) if x[0] == 'inspect']
        print(len(error), 'errors,', len(correct), 'correct,', len(inspect), 'inspect') 
        for x in error:
            index = x[0]
            event = self.eventid[index]
            print(f'{event}: {x[1][1]}')
        maunual_edits = {
            "S240921cw": ['correct', 'not triggered', 0, 0, ''], # moon too close ?
            "S241125n": ['correct', 'triggered', 900, 0.5, ''], # the Swift/Bat coincident detection
            "S241130n": ['correct', 'not triggered', 0, 0, ''] # sun too close ?
        }
        for key, value in maunual_edits.items():
            if key in self.eventid:
                i = self.eventid.index(key)
                trigger_status[i] = value
        return trigger_status
    

class NewEvents():
    def __init__(self, params, trigger_status):
        self.params = params
        self.trigger_status = trigger_status

    def generate_cadence_dates(input_dates):
        cadence = [7, 14, 21, 28, 40, 50]
        result = []
        for input_date_str in input_dates:
            if input_date_str == '':
                result.append('')
            else:
                input_date = datetime.strptime(input_date_str, '%Y-%m-%dT%H:%M:%S.%f')
                date_only = datetime(input_date.year, input_date.month, input_date.day)
                new_dates = [(date_only + timedelta(days=days)).strftime('%Y-%m-%d') for days in cadence]
                result.append(new_dates)
        return result

    def save_data(self):  
        ids = [x[0] for x in self.params]
        far_format = ["{:.1e}".format(x[13]) if x[9] > 1000 else "{:.1f}".format(x[9]) for x in self.params]
        mass_format = [round(x[22]) for x in self.params]
        dist_format = [round(x[13]/10**3, 2) for x in self.params]
        a50_format = [round(x[17]) for x in self.params]
        a90_format = [round(x[16]) for x in self.params]
        mjd = [round(Time(x[15], format='fits').mjd) for x in self.params] 
        gcnid = [Time(x[15], format='isot', scale='utc').iso.split('.')[0].replace(' ', 'T') for x in self.params]
        trigger = [x[1] for x in self.trigger_status]
        total_time = [x[2] if len(x) > 2 else '' for x in self.trigger_status]
        probability = [round(x[3], 2) if len(x) > 2 else '' for x in self.trigger_status]
        start = [x[4] if len(x) > 2 else '' for x in self.trigger_status]
        obs_cadence = self.generate_cadence_dates(start)
        new_events_df = pd.DataFrame({
            'graceids': ids,
            "GW MJD": mjd,
            '90% Area (deg2)': a90_format,
            '50% Area (deg2)': a50_format,
            'Distance (Gpc)': dist_format,
            'FAR (years/FA)': far_format,
            'Mass (M_sol)': mass_format,
            'gcnids': gcnid,
            'trigger': trigger,
            'plan time': total_time,
            'plan probability': probability,
            'plan start': start, 
            'cadence': obs_cadence
            })
        new_events_df['FAR (years/FA)'] = pd.to_numeric(new_events_df['FAR (years/FA)'], downcast='integer')

        new_events_df.set_index('graceids', inplace=True)
        df_for_dict = new_events_df.drop(columns=['plan time', 'plan probability', 'plan start', 'cadence'])
        new_events_dict = df_for_dict.to_dict(orient='index')

        with open('dicts/events_dict_O4b.json', 'r') as file:
            events_dict_add = json.load(file)

        # add any new events to saved dict
        for key in new_events_dict.keys(): 
            if key not in events_dict_add.keys(): 
                events_dict_add[key] = {}
                events_dict_add[key]['gw'] = new_events_dict[key]
                events_dict_add[key]['crossmatch'] = {} 
                events_dict_add[key]['flare'] = {}
            
            keys_to_update = ['Days since GW', '90% Area (deg2)', '50% Area (deg2)', 'Distance (Gpc)', 'FAR (years/FA)', 'Mass (M_sol)', 'gcnids', 'trigger']
            for subkey in new_events_dict[key].keys():
                if subkey in keys_to_update:
                    events_dict_add[key]['gw'][subkey] = new_events_dict[key][subkey]
            
            # Add subkeys for total times and probability for triggered events and good events that werent triggered (likely failed on plan)
            if new_events_dict[key]['trigger'] in ['triggered', 'bad trigger'] or key in ['S241210cw', 'S241130n', 'S241129aa', 'S240924a']:        
                events_dict_add[key]['gw']['trigger plan'] = {}
                events_dict_add[key]['gw']['trigger plan']['time'] = new_events_df.at[key, 'plan time'] if 'plan time' in new_events_df.columns else 0
                events_dict_add[key]['gw']['trigger plan']['probability'] = new_events_df.at[key, 'plan probability'] if 'plan probability' in new_events_df.columns else 0.0
                events_dict_add[key]['gw']['trigger plan']['start'] = new_events_df.at[key, 'plan start'] if 'plan start' in new_events_df.columns else ''
                events_dict_add[key]['gw']['trigger plan']['cadence'] = new_events_df.at[key, 'cadence'] if 'cadence' in new_events_df.columns else ''

        save = input("Save dictionary with new events added? (yes/no): ").strip().lower()
        if save == 'yes':
            with open('dicts/events_dict_O4b.json', 'w') as file:
                json.dump(events_dict_add, file)
            print("New events saved to dictionary.")
        else:
            print("New events not saved.") 
        return new_events_df


class AGNCrossmatch():
    def __init__(self, events_dict):
        self.events_dict = events_dict

    def get_zfps_status(self):
        # make this automatic
        trigger_list = ['S240919bn', 'S240923ct', 'S241006k', 'S241009em', 'S241114y']
        good_events = [key for key, value in self.events_dict.items() if value['gw']['Mass (M_sol)'] > 60]