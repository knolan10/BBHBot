import pandas as pd
from pandas import json_normalize
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
import subprocess
from ligo.gracedb.rest import GraceDb
g = GraceDb()  
from penquins import Kowalski

#credentials
with open('bot/FlareBotCredentials.yaml', 'r') as file:
    credentials = yaml.safe_load(file)
github_token = credentials['github_token']
kowalski_password = credentials['kowalski_password']
fritz_token = credentials['fritz_token']    
allocation = credentials['allocation']  


class GetSuperevents():
    def __init__(self, path_events_dictionary, mlp_modelpath, event_source, kafka_response=None):
        self.path_events_dictionary = path_events_dictionary
        self.mlp_modelpath = mlp_modelpath
        self.event_source = event_source
        self.kafka_response = kafka_response

    # todo : cut unused params returned
    # todo : add a date to the gracedb query so we aren't getting all of 04b
    # todo : add option to update all events, ie with update alerts
    
    """
    get new events that haven't been processed yet
    use get_new_events to return : 
    superevent_id, event_page, alert_type, instrument, pipeline, group, significant, prob_bbh, prob_ter, 
    far_format, skymap_url, date, fritz_dateid, distmean, diststd, dateobs_str, a90, a50, skymap_str, zmin,
    zmax, skymap, mass
    """
    def read_from_gracedb(self, ids, files):
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
        response = [requests.get(url).text for url in urls_save]
        return response


    def get_params(self, response):
        try:
            dict = xmltodict.parse(response)
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
            return superevent_id, event_page, alert_type, instrument, pipeline, group, significant, prob_bbh, prob_ter, far_format, skymap_url, date, fritz_dateid
        except:
            print(f'error loading xml: {response}')

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
            return distmean, diststd, dateobs_str, a90, a50, skymap_str, zmin, zmax, skymap
        except:
            print(f'error loading skymap {skymap_url}')
            return 'None'
        
    def m_total_mlp(self, MLP_model, dl_bbh, far, dl_bns=168.):
        z = cos.z_at_value(cosmo.luminosity_distance, dl_bbh * u.Mpc, method='bounded')
        X = np.array([np.log10(dl_bbh / dl_bns), np.log10(1 + z), np.log10(far)])
        X = X.reshape(1, -1)
        mass = MLP_model.predict(X)[0]
        return 10. ** mass

    def get_new_events(self):
        if self.event_source == 'gracedb':
            event_iterator = g.superevents('runid: O4b SIGNIF_LOCKED')
            graceids_all = [superevent['superevent_id'] for superevent in event_iterator]
            print(len(graceids_all), 'significant superevents in O4b')
            responses = [g.superevent(id) for id in graceids_all]
            data_all = [r.json() for r in responses]
            with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
                events_dict_add = json.load(file)
            new_events = [(i, j) for i, j in zip(graceids_all, data_all) if i not in list(events_dict_add.keys())]
            graceids = [x[0] for x in new_events]
            data = [x[1] for x in new_events]
            response = self.read_from_gracedb(graceids, data)
        elif self.event_source == 'kafka':
            response = [self.kafka_response]
        gcn_params = [self.get_params(url) for url in response]
        low_prob_bbh = [x for x in gcn_params if x[7] < 0.5 or x[8] > 0.3]
        params = [x for x in gcn_params if x[7] > 0.5 and x[8] < 0.3]
        print(f'{len(params)} events (cut {len(low_prob_bbh)} low prob bbh events)')
        skymap_urls = [x[10] for x in params]
        skymap_data = [self.extract_skymap_params(url) for url in skymap_urls]
        # mass
        dist = [x[0] for x in skymap_data]
        far = [x[9] for x in params]
        MLP = pickle.load(open(self.mlp_modelpath, 'rb'))
        mass = [self.m_total_mlp(MLP, d, f, dl_bns=168.) for d, f in zip(dist, far)]
        return [list(i)+list(j)+[k] for i,j,k in zip(params, skymap_data, mass)]

class Fritz():
    def __init__(self, eventid, dateid, a90, far, mass):
        self.eventid = eventid
        self.dateid = dateid
        self.a90 = a90
        self.far = far
        self.mass = mass    

    def query_fritz_observation_plans(self, allocation, token):
        headers = {'Authorization': f'token {token}'}
        endpoint = f'https://fritz.science/api/allocation/observation_plans/{allocation}?numPerPage=1000'
        response = requests.request('GET', endpoint, headers=headers)
        if response.status_code == 200:
            json_string = response.content.decode('utf-8')
            json_data = json.loads(json_string)            
            return json_data
        else:
            print(response.status_code)
            return None
        
    # get the statistics for a potential observation plan
    def determine_trigger_status(self, observation_plans, eventid, dateid, a90, far, mass):
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
        
    def get_trigger_status(self):    
        plans = self.query_fritz_observation_plans(allocation, fritz_token)
        observation_plan_requests = plans['data']['observation_plan_requests']
        print(f'There are currently {plans['data']['totalMatches']} observation plans generated')
        trigger_status = [self.determine_trigger_status(observation_plan_requests, i, j, a, f, m) 
                          for i,j,a,f,m in zip(self.eventid, self.dateid, self.a90, self.far, self.mass)]
        error = [(i, x) for i, x in enumerate(trigger_status) if x[0] == 'error']
        correct = [(i, x) for i, x in enumerate(trigger_status) if x[0] == 'correct']
        inspect = [(i, x) for i, x in enumerate(trigger_status) if x[0] == 'inspect']
        print(f'{len(error)} errors, {len(correct)} correct, {len(inspect)} inspect') 
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
    

class NewEventsToDict():
    def __init__(self, params, trigger_status, path_events_dictionary, check_before_run=False):
        self.params = params
        self.trigger_status = trigger_status
        self.check_before_run = check_before_run
        self.path_events_dictionary = path_events_dictionary

    def generate_cadence_dates(self,input_dates):
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

        with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
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

        if not self.check_before_run:
            save = input("Save dictionary with new events added? (yes/no): ").strip().lower()
            if save == 'yes':
                with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'w') as file:
                    json.dump(events_dict_add, file)
                print("New events saved to dictionary.")
            else:
                print("New events not saved.") 
        else: # save automatically
            with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'w') as file:
                json.dump(events_dict_add, file)
            print("New events saved to dictionary.")
        return new_events_df


class KowalskiCrossmatch():
    def __init__(self, localization_name, skymap_str, dateobs, zmin, zmax, path_events_dictionary, contour=90, mindec=-90, testing=False): 
        self.localization_name = localization_name
        self.skymap_str = skymap_str
        self.dateobs = dateobs
        self.zmin = zmin
        self.zmax = zmax
        self.path_events_dictionary = path_events_dictionary
        self.mindec = mindec
        self.contour = contour
        self.testing = testing
        self.kowalski_password = kowalski_password # defined above
        self.kowalski = self.connect_kowalski()

    def connect_kowalski(self):
        instances = {
            "kowalski": {
                "name": "kowalski",
                "host": "kowalski.caltech.edu",
                "protocol": "https",
                "port": 443,
                "username": "knolan",
                "password": self.kowalski_password,
                "timeout": 6000
            },
            "gloria": {
                "name": "gloria",
                "host": "gloria.caltech.edu",
                "protocol": "https",
                "port": 443,
                "username": "knolan",
                "password": self.kowalski_password,
                "timeout": 6000
            }
        }
        kowalski = Kowalski(instances=instances)
        return kowalski

    def check_events_to_crossmatch(self):
        with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
            events_dict_add = json.load(file)
        do_crossmatch = [key for key, value in events_dict_add.items() if not value['crossmatch']]
        print(f'{len(do_crossmatch)} events are missing crossmatch: {do_crossmatch}')
        return do_crossmatch

    def load_skymap_to_kowalski(self, kowalski, localization_name, skymapstring, date, contour, machine):
        skymap_data = {
            'localization_name': localization_name, 
            'content': skymapstring,
        }
        kowalski.api('put', 'api/skymap', data={'dateobs': date, 'skymap': skymap_data, 'contours': contour}, name=machine)

    def crossmatch_catnorth(self, kowalski, localization_name, contour, date, zmin, zmax, mindec):
        """
        crossmatch catnorth with the ligo skymap
        """
        query = {
            "query_type": "skymap",
            "query": {
                "skymap": {
                    "localization_name": localization_name,
                    "contour": contour,
                    "dateobs": date
                },
                "catalog": 'CatNorth',
                "filter": {'z_ph': {"$gte": zmin, "$lte": zmax}, 'dec': {"$gte": mindec}}, 
                "projection": {"ra": 1, "dec": 1, "z_xp_nn": 1},
            },
        }
        response_catnorth_localization = kowalski.query(query=query)
        selected_agn = response_catnorth_localization.get('gloria', {}).get('data', [])
        print(f'{len(selected_agn)} CATNorth AGN found in localization volume for {localization_name}')
        return selected_agn

    def crossmatch_quaia(self, kowalski, localization_name, contour, date, zmin, zmax, mindec):    
        """
        crossmatch quaia_G20.5 with the ligo skymap
        """
        query = {
            "query_type": "skymap",
            "query": {
                "skymap": {
                    "localization_name": localization_name,
                    "contour": contour,
                    "dateobs": date
                },
                "catalog": "quaia_G20.5",
                "filter": {'redshift_quaia': {"$gte": zmin, "$lte": zmax}, 'dec': {"$gte": mindec}}, 
                "projection": {"ra": 1, "dec": 1, 'redshift_quaia': 1, 'unwise_objid': 1},
            },
        }
        response_quaia_localization = kowalski.query(query=query, name='kowalski')
        selected_agn = response_quaia_localization.get('kowalski', {}).get('data', [])
        converted_selected_agn = [{**entry, '_id': str(entry['_id'])} for entry in selected_agn]
        print(f'{len(converted_selected_agn)} Quaia AGN found in localization volume for {localization_name}')
        return converted_selected_agn

    def delete_skymaps(self, kowalski, dateobs, localization_name, machine):
        """
        delete skymaps for cleanup
        """
        kowalski.api('delete', 'api/skymap', data={'dateobs': dateobs, 'localization_name': localization_name}, name = machine)


    def get_crossmatches(self): 
        """
        get catnorth and quaia crossmatches
        """
        kowalski = self.kowalski
        localization_name = self.localization_name
        skymap_str = self.skymap_str
        contour = self.contour
        date = self.dateobs
        zmin = self.zmin
        zmax = self.zmax
        mindec = self.mindec

        [self.load_skymap_to_kowalski(kowalski,l,s,d,contour,'gloria') 
         for l,s,d in zip(localization_name, skymap_str, date)]
        [self.load_skymap_to_kowalski(kowalski,l,s,d,contour,'kowalski') 
         for l,s,d in zip(localization_name, skymap_str, date)]
        catnorth = [self.crossmatch_catnorth(kowalski,l,contour,d,zn,zx,mindec)
                    for l,d,zn,zx in zip(localization_name, date, zmin, zmax)]
        quaia = [self.crossmatch_quaia(kowalski,l,contour,d,zn,zx,mindec)
                    for l,d,zn,zx in zip(localization_name, date, zmin, zmax)]
        if not self.testing:
        # save coords for catnorth crossmatch
            crossmatch_dict = {id: {'agn_catnorth': coords} for id, coords in zip(localization_name, catnorth)}
            with gzip.open(f'{self.path_events_dictionary}/dicts/crossmatch_dict_O4b.gz', 'rb') as f:
                crossmatch_dict_add = pickle.load(f)
            for key, value in crossmatch_dict.items():
                if key not in crossmatch_dict_add:
                    crossmatch_dict_add[key] = value
                    print (key, 'added')
                else:
                    print(key, 'already in dictionary')
            with gzip.open(f'{self.path_events_dictionary}/dicts/crossmatch_dict_O4b.gz', 'wb') as f:
                f.write(pickle.dumps(crossmatch_dict_add))
            # save stats on crossmatch
            crossmatch_dict_stats = {id: {'n_agn_catnorth': len(c), 'n_agn_quaia': len(q)} for id, c, q in zip(localization_name, catnorth, quaia)}
            with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
                events_dict_add = json.load(file)
            for key, value in crossmatch_dict_stats.items():
                if key in events_dict_add:
                    events_dict_add[key]['crossmatch'] = value
                else:
                    print(key, 'not in dictionary')
            with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'w') as file:
                json.dump(events_dict_add, file)

        [self.delete_skymaps(kowalski, d, l, 'gloria') for d, l in zip(date, localization_name)]
        [self.delete_skymaps(kowalski, d, l, 'kowalski') for d,l in zip(date, localization_name)]

        return catnorth, quaia

class PushEventsPublic():
    def __init__(self, path_events_dictionary, testing=False, verbose=True): 
        self.path_events_dictionary = path_events_dictionary
        self.testing = testing
        self.verbose = verbose

    def push_changes_to_repo(self):
        dir_path = '../../events_summary'
        commit_message = 'automated push of new events'
        try:
            remote_url = f'https://{github_token}@github.com/knolan10/BBHBot/events_summary'

            subprocess.run(['git', '-C', dir_path, 'remote', 'set-url', 'origin', remote_url], check=True)

            subprocess.run(['git', '-C', dir_path, 'add', '.'], check=True)

            result = subprocess.run(['git', '-C', dir_path, 'status', '--porcelain'], capture_output=True, text=True)
            if not result.stdout.strip():
                print("No changes to commit. Pushing existing commits.")
            else:
                subprocess.run(['git', '-C', dir_path, 'commit', '-m', commit_message], check=True)

            subprocess.run(['git', '-C', dir_path, 'push', 'origin', 'main'], check=True)
            print("Changes pushed to the repository successfully.")
        except subprocess.CalledProcessError as e:
            print(f"An error occurred: {e}")
            print(f"Error output: {e.stderr}")
            print(f"An error occurred: {e}")

    def plot_trigger_timeline(self, trigger_df):
        plt.figure(figsize=(10, 2))
        plt.scatter(trigger_df['GW MJD'], [0.1] * len(trigger_df), s=trigger_df['Mass (M_sol)']*10, alpha=0.5)
        plt.xlabel('Date (MJD)', fontsize=18)
        plt.yticks([])
        plt.title('Timeline of Triggered Observations', fontsize=20)
        for i, row in trigger_df.iterrows():
            plt.annotate(f'{row["Mass (M_sol)"]}M$_{{\\odot}}$', (row['GW MJD'], 0.078), textcoords="offset points", xytext=(0,10), ha='center')
        ax = plt.gca()
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_position('zero')
        plt.xticks(fontsize=14)
        plt.ylim(0, 0.2)
        plt.show()

    def format_and_push(self):
        with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
            events_dict_add = json.load(file)
        # convert back to df
        restructured_dict = {key: {'graceids': key, **value['gw']} for key, value in events_dict_add.items()}
        df_full = pd.DataFrame.from_dict(restructured_dict, orient='index')
        df_full = df_full.reset_index(drop=True)
        trigger_plan = json_normalize(df_full['trigger plan'])
        df_full = pd.concat([df_full, trigger_plan], axis=1)
        # make gracids into links
        gracedbids = df_full['graceids']
        gracedb_urls = [f'https://gracedb.ligo.org/superevents/{id}/view/' for id in gracedbids]
        gracedb_links = [f'[{id}]({url})' for id, url in zip(gracedbids, gracedb_urls)]
        df_full['graceids'] = gracedb_links
        # make gcnids into links
        fritzids = df_full['gcnids']
        fritz_urls = [f'https://fritz.science/gcn_events/{id}' for id in fritzids]
        fritz_links = [f'[{id}]({url})' for id, url in zip(fritzids, fritz_urls)]
        df_full['gcnids'] = fritz_links
        #remove trigger_plan, gcnids
        df = df_full.drop(columns=['trigger plan', 'gcnids', 'time', 'probability', 'start', 'cadence'])
        # put newest events at the top
        df = df.sort_values(by='GW MJD', ascending=False)
        df = df.reset_index(drop=True)
        #custom comments
        df['comments'] = ''
        df.loc[df['graceids'].str.contains('S240921cw'), 'comments'] = 'moon too close'
        df.loc[df['graceids'].str.contains('S241125n'), 'comments'] = 'Swift/Bat coincident detection'
        df.loc[df['graceids'].str.contains('S241130n'), 'comments'] = 'sun too close'

        # priority df
        df_priority = df_full.drop(columns=[col for col in ['trigger plan', 'cadence', 'start'] if col in df_full.columns])
        confident = df_priority[df_priority['FAR (years/FA)'] > 10] #FAR is in units of years per false alert 
        high_mass = df_priority[df_priority['Mass (M_sol)'] > 60]
        low_area = df_priority[df_priority['90% Area (deg2)'] < 1000]
        highmass_lowarea = pd.merge(high_mass, low_area)  
        priority = pd.merge(highmass_lowarea, confident)
        if self.verbose:
            print(len(priority), 'O4b events with FAR > 10 and mass > 60 and area < 1000 sq deg')
        priority = priority.sort_values(by='GW MJD', ascending=False)
        priority = priority.reset_index(drop=True)
        # #manual edits
        priority.loc[priority['GW MJD'] == 60572, 'gcnids'] = '[2024-09-19T06:15:59](https://fritz.science/gcn_events/2024-09-19T06:15:59)'
        # #add comments
        priority['comments'] = ''
        priority.loc[priority['graceids'].str.contains('S241210cw'), 'comments'] = 'Sun too close'
        priority.loc[priority['graceids'].str.contains('S241130n'), 'comments'] = 'Sun too close'
        priority.loc[priority['graceids'].str.contains('S241129aa'), 'comments'] = 'Southern target'
        priority.loc[priority['graceids'].str.contains('S240924a'), 'comments'] = 'Southern target'
        #remove nan gcnids
        priority['gcnids'] = priority['gcnids'].apply(lambda x: '' if 'nan' in x else x)

        # trigger df
        trigger_df = df_full[df_full['trigger'] == 'triggered']
        trigger_df = trigger_df.drop(columns=['trigger', 'trigger plan'])
        trigger_df = trigger_df.iloc[::-1].reset_index(drop=True)
        trigger_df = trigger_df.reset_index(drop=True)
        #manual edits
        trigger_df.loc[trigger_df['GW MJD'] == 60572, 'gcnids'] = '[2024-09-19T06:15:59](https://fritz.science/gcn_events/2024-09-19T06:15:59)'
        #add comments
        trigger_df['comments'] = ''
        trigger_df.loc[trigger_df['graceids'].str.contains('S241125n'), 'comments'] = 'Swift/Bat coincident detection'
        if self.verbose:
            self.plot_trigger_timeline(trigger_df)

        #trigger errors
        error_triggers = df_full[(df_full['trigger'] == 'bad trigger') | 
                         (df_full['trigger'] == 'missed trigger') |
                         (df_full['trigger'] == 'nan') |
                         (df_full['trigger'] == 'no plan') |
                         (df_full['trigger'] == 'no valid plan')]
        error_triggers = error_triggers.drop(columns=['trigger', 'trigger plan', 'cadence'])
        error_triggers = error_triggers.iloc[::-1].reset_index(drop=True)
        error_triggers = error_triggers.reset_index(drop=True)
        #manual edits
        error_triggers.loc[error_triggers['GW MJD'] == 60573, 'gcnids'] = '[2024-09-20T07:34:24](https://fritz.science/gcn_events/2024-09-20T07:34:24)'
        error_triggers.loc[error_triggers['GW MJD'] == 60568, 'gcnids'] = '[2024-09-15T10:51:51](https://fritz.science/gcn_events/2024-09-15T10:51:51)'
        #add comments
        error_triggers['comments'] = 'fails mass criteria'
        error_triggers['comments'] = 'fails mass criteria'
        error_triggers.loc[error_triggers['GW MJD'] == 60694, 'comments'] = 'plan has zero observations'

        # format to push to repo
        df = df.fillna('')
        priority = priority.fillna('')  
        trigger_df = trigger_df.fillna('')
        error_triggers = error_triggers.fillna('')

        trigger_df['cadence'] = trigger_df['cadence'].apply(lambda dates: [date.replace('-', '.') for date in dates] if isinstance(dates, list) else dates)
        markdown_table_O4b = df.to_markdown(index=False)
        markdown_table_O4b_priority = priority.to_markdown(index=False)
        markdown_table_trigger = trigger_df.to_markdown(index=False)
        markdown_table_error_triggers = error_triggers.to_markdown(index=False)
        if not self.testing:
            with open('../../events_summary/O4b.md', 'w') as f:
                f.write(markdown_table_O4b)

            with open('../../events_summary/O4b_priority.md', 'w') as f:
                f.write(markdown_table_O4b_priority)

            with open('../../events_summary/trigger.md', 'w') as f:
                f.write(markdown_table_trigger)

            with open('../../events_summary/error_trigger.md', 'w') as f:
                f.write(markdown_table_error_triggers)

            self.push_changes_to_repo()

        return df, priority, trigger_df, error_triggers

