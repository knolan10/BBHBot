import pickle
import gzip
import json
import pandas as pd
from datetime import datetime
from astropy.time import Time
import requests
import os
import re
from io import StringIO
import io
import seaborn as sns
import matplotlib.pyplot as plt 
import math


class PhotometryStatus:
    def __init__(self, observing_run='O4c', path_data=None):
        self.observing_run = observing_run
        self.path_data = path_data   

    def show_status(self):
        try:
            with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'r') as file:
                events_dict = json.load(file)
        except:
            print('observing_run must be O4a, O4b, or O4c')
            return
        #TODO: automate
        trigger_list = ['S240919bn', 'S240923ct', 'S241006k', 'S241009em', 'S241114y', 'S250319bu']
        good_events = [key for key, value in events_dict.items() if value['gw']['Mass (M_sol)'] > 60 
                    and value['gw']['90% Area (deg2)'] < 1000
                    and value['gw']['FAR (years/FA)'] > 10]
        print(f'{len(events_dict) - len(good_events)} / {len(events_dict)} events in {self.observing_run} are not priority')
        good_events_dict = {key: events_dict[key] for key in good_events if key in events_dict}
        # put into df for display
        zfps_status_df = pd.DataFrame(
            {
                'ID': good_events_dict.keys(),
                'Date last zfps': [value['flare']['date_last_zfps'] if 'date_last_zfps' in value['flare'] else '' for value in good_events_dict.values()],
                'Status': '',
                'Trigger': [True if key in trigger_list else '' for key in good_events_dict.keys()]
            }
        )
        # do any good event have no crossmatched AGN
        no_crossmatch_agn = [key for key, value in good_events_dict.items() if value['crossmatch']['n_agn_catnorth'] == 0]
        # assign event status 
        current_date = datetime.now()
        def assign_status(row):
            if row['ID'] in no_crossmatch_agn or row['Date last zfps'] == 'NA':
                return 'no AGN'
            elif row['Date last zfps'] == '':
                return 'needs ZFPS'
            else:
                try:
                    date_last_zfps = datetime.strptime(row['Date last zfps'], '%Y-%m-%d %H:%M:%S.%f')
                    if (current_date - date_last_zfps).days <= 200:
                        return 'update ZFPS'
                    else:
                        return 'complete'
                except (ValueError, TypeError):
                    return 'error'
        zfps_status_df['Status'] = zfps_status_df.apply(assign_status, axis=1)
        zfps_status_df = zfps_status_df.iloc[::-1].reset_index(drop=True)
        return zfps_status_df

class PhotometryCoords():
    def __init__(self, action, graceid, catalog, verbose, path_data, observing_run):
        self.action = action
        self.graceid = graceid
        self.catalog = catalog
        self.verbose = verbose
        self.path_data = path_data
        self.observing_run = observing_run
        self.path_photometry = f'{self.path_data}/flare_data/ZFPS/'  

    def get_agn_coords(self):
        """"
        get AGN coords for a given event
        Depending on action variable, will get all coords, only coords we have no photometry, or coords of existing photometry and dates to update photometry
        If retrieving new coords order them based on skymap probability
        input: graceid (string), catalog (list of string names of catalogs), action ('all', 'new', 'update') 
        """
        # open the stored event info
        with gzip.open(f'{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz', 'rb') as f:
            crossmatch_dict = pickle.load(f)
        with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'r') as file:
            events_dict = json.load(file)
        coords_catnorth = []
        coords_quaia = []
        if 'catnorth' in self.catalog:
            coords_catnorth = crossmatch_dict[self.graceid]['agn_catnorth']
        if 'quaia' in self.catalog:
            coords_quaia = crossmatch_dict[self.graceid]['agn_quaia']
        all_coords = coords_catnorth + coords_quaia       
        #remove AGN below dec = -30 as rough ZTF footprint
        ztf_coords = [d for d in all_coords if d.get('dec', 0) >= -30]
        gw_jd = events_dict[self.graceid]['gw']['GW MJD'] + 2400000.5
        two_year_baseline = gw_jd - 365*2
        if self.action == 'all':
            print(f'about {len(ztf_coords)} / {len(all_coords)} coords should be in ZTF footprint')
            return ztf_coords, two_year_baseline
        names = [str(x['ra']) + '_' + str(x['dec']) for x in ztf_coords]
        path = self.path_photometry #path to where photometry is stored locally
        if self.action == 'new':
            new_coords = [coords for coords,name in zip(ztf_coords, names) if not os.path.exists(path + name + '.gz')]
            print(f'{len(new_coords)} / {len(all_coords)} total coords dont have photometry')
            return new_coords, two_year_baseline
        if self.action == 'update':
            if events_dict[self.graceid]['flare']:
                date_zfps = events_dict[self.graceid]['flare']['date_last_zfps'] 
                print(f'last photometry request for {self.graceid} was on {date_zfps}')
            else:
                print(f'Error: no photometry for {self.graceid}')  
                return
            existing_coords = [coords for coords,name in zip(ztf_coords, names) if os.path.exists(path + name + '.gz')]
            print(f'Found saved photometry for {len(existing_coords)} / {len(all_coords)} coords crossmatched')
            # if the df is empty, get two year baseline
            existing_photometry = [pd.read_pickle(path + file + '.gz', compression='gzip') for file in names if os.path.exists(path + file + '.gz')]
            latest_dates = [round(df['jd'].max()) if not df.empty else 2459367.5 for df in existing_photometry] 
            current_date = Time.now().jd
            # dont request if photometry from within the week, or we already have 200 days post gw
            filtered_coords = [x for x, date in zip(existing_coords, latest_dates) if current_date - date > 7 and date - gw_jd < 200] 
            num_invalid = len(latest_dates)-len(filtered_coords)
            if num_invalid > 0:
                print(f'{num_invalid} coords have photometry within a week or are outside 200 days post GW')
            elif len(filtered_coords) == 0:
                print(f'No coords valid for update photometry')
            else:
                print(f'{len(filtered_coords)} coords are valid for update photometry')
            #convert mjd to jd
            dates = [date for date in latest_dates if current_date - date  > 7 and date - gw_jd < 200]
            return filtered_coords, dates
    
    def custom_update_batching(self, coords, dates, threshold=60):
        """
        This is for the update mode only
        ZFPS cant take multiple dates for batched requests, so batch ourselves to reduce the number of batches submitted
        while also reducing the extent to which we request photometry for time periods we already have coverage of
        Threshold will set the window size that we will batch together
        """
        combined = sorted(zip(dates, coords), key=lambda x: x[0])
        sorted_dates, sorted_coords = zip(*combined)
        grouped_dates = []
        grouped_coords = []
        current_group_dates = []
        current_group_coords = []
        for i in range(len(sorted_dates)):
            if not current_group_dates or sorted_dates[i] - current_group_dates[-1] <= threshold:
                current_group_dates.append(sorted_dates[i])
                current_group_coords.append(sorted_coords[i])
            else:
                grouped_dates.append(current_group_dates)
                grouped_coords.append(current_group_coords)
                current_group_dates = [sorted_dates[i]]
                current_group_coords = [sorted_coords[i]]
        # Append the last group if it exists
        if current_group_dates:
            grouped_dates.append(current_group_dates)
            grouped_coords.append(current_group_coords)
        single_dates = [min(group) for group in grouped_dates]
        print(f'After batching dates with window size {threshold}, created {len(single_dates)} batches')
        return single_dates, grouped_coords
    
    @staticmethod
    def flatten_radec(coordlist):
        """
        just some formatting for the update scenario
        """
        fixed = []
        for item in coordlist:
            if isinstance(item, list) and any(isinstance(subitem, list) for subitem in item):
                fixed.extend(subitem for subitem in item if isinstance(subitem, list))
            else:
                fixed.append(item)
        return fixed
    
    def format_for_zfps(self, coords, date):
        """
        get formatting and batching for ZFPS submission
        """
        with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'r') as file:
            events_dict = json.load(file)
        ra = [val['ra'] for val in coords]
        dec = [val['dec'] for val in coords]
        if len(coords) == 0:   
            print('no AGN to submit')
            events_dict[self.graceid]['flare'] = {'date_last_zfps': 'no AGN observable by ZTF'}
            with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'w') as file:
                json.dump(events_dict, file) 
            return
        else:
            ralist = [ra[i:i+1500] for i in range(0, len(ra), 1500)]
            declist = [dec[i:i+1500] for i in range(0, len(dec), 1500)]
            if self.action == 'update':
                date = [date] * len(ralist)
            print(f'Submit in {len(ralist)} batches')
            return ralist, declist, date
        
    def replace_scientific_notation(self, ra_list, dec_list):
        """
        addressing bug where sometimes coords are formatted in scientific notation, which ZFPS can't handle
        """
        def is_scientific_notation(num):
            return 'e' in f"{num}" or 'E' in f"{num}"
        def process_list(lst):
            if all(isinstance(i, list) for i in lst):
                sci = [num for sublist in lst for num in sublist if is_scientific_notation(num)]
                if len(sci) > 0:
                    print(f'Found sci: {sci}')
                    print('If there is a number in scientific notation that shouldn\'t be rounded to zero, need to address manually')
                return [[0 if is_scientific_notation(num) else num for num in sublist] for sublist in lst]
            else:
                sci = [num for num in lst if is_scientific_notation(num)]
                if len(sci) > 0:
                    print(f'Found sci: {sci}')
                return [0 if is_scientific_notation(num) else num for num in lst]
        ra_list = process_list(ra_list)
        dec_list = process_list(dec_list)
        return ra_list, dec_list
        
    def get_photometry_coords(self):
        coords, date = self.get_agn_coords()
        num_agn = len(coords)
        if self.action == 'update':
            grouped_dates, grouped_coords = self.custom_update_batching(coords, date)
            formatted = [self.format_for_zfps(i,j) for i,j in zip(grouped_coords, grouped_dates)]
            ra_unflattened = [x[0] for x in formatted]
            ra = self.flatten_radec(ra_unflattened)
            dec_unflattened = [x[1] for x in formatted]
            dec = self.flatten_radec(dec_unflattened)
            jd_unflattened = [x[2] for x in formatted] 
            jd = [item for sublist in jd_unflattened for item in (sublist if isinstance(sublist, list) else [sublist])]
            print(f'After batching for ZFPS, retrieved {len(date)} objects in {len(jd)} batches')
        else:
            ra,dec,jd = self.format_for_zfps(coords, date)
            jd = [jd] * len(ra)
        # handle events that have > 15000 AGN to submit (note - this should always be in batches of 1500 max)
        # might be better not to assume max size of 1500, but something is wrong in code if this isn't true
        # therefore assume we can submit 10 batches at a time
        if num_agn > 15000:
            num_batches_for_limit = math.ceil((len(ra)) / 10)
            for i in range(1,num_batches_for_limit):
                start_index = i * 10
                end_index = i * 10 + 10
                number_queued = sum(len(x) for x in ra[start_index:end_index])
                name_queued = f'{self.graceid}_{i}'
                # FIXME: this path wont work when running outside of this directory
                self.queue_photometry(ra[start_index:end_index], 
                                      dec[start_index:end_index], 
                                      jd[start_index:end_index], 
                                      number_queued)

            # to submit now
            ra, dec, jd = ra[:10], dec[:10], jd[:10]
            num_agn = sum([len(x) for x in ra]) 
            print(f'Retrieved {num_agn} AGN for submission now')

        return ra, dec, jd, num_agn
    
    def queue_photometry(self, ra, dec, jd, number_to_submit):
        """
        If we are at request limit, save for later submission
        """
        file_path = f'{self.path_data}/flare_data/queued_for_photometry/{self.graceid}.json'
        if os.path.exists(file_path):
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            f'{self.path_data}/flare_data/queued_for_photometry/{self.graceid}_{timestamp}.json'
        data = {
            "ra": ra,
            "dec": dec,
            "jd": jd,
            "number_to_submit": number_to_submit,
            "action": self.action
        }
        print(f"Saving {len(ra)} queued photometry to {file_path}")
        with open(file_path, 'w') as file:
            json.dump(data, file, indent=4)

    def retrieve_queue_photometry(path_data):
        """
        Retrieve id, ra, dec, jd, dateobs for all queued requests
        """
        photometry_data = []
        
        path_queued_photometry = f'{path_data}/flare_data/queued_for_photometry'
        for file_name in os.listdir(path_queued_photometry):
            if file_name.endswith('.json'):
                file_path = os.path.join(path_queued_photometry, file_name)
                with open(file_path, 'r') as file:
                    data = json.load(file)
                    match = re.match(r"^(.*?)(?:_\d{14})?\.json$", file_name)
                    id = match.group(1) if match else os.path.splitext(file_name)[0]
                    ra = data.get("ra")
                    dec = data.get("dec")
                    jd = data.get("jd")
                    number_to_submit = data.get("number_to_submit")
                    action = data.get("action")
                    photometry_data.append((id, ra, dec, jd, number_to_submit, action, file_name))
        return photometry_data
    
    def move_complete_queued_photometry(file_name, path_data):
        """
        Move the file to a different directory
        """
        path_queued_photometry = f'{path_data}/flare_data/queued_for_photometry'
        path_complete_queued_photometry = f'{path_data}/flare_data/completed_queued_photometry'
        source_path = os.path.join(path_queued_photometry, file_name)
        destination_path = os.path.join(path_complete_queued_photometry, file_name)
        if os.path.exists(source_path):
            os.rename(source_path, destination_path)
            print(f"Moved {file_name} to {path_complete_queued_photometry}")
        else:
            print(f"{file_name} not found in {path_queued_photometry}")


class GetPhotometry():
    def __init__(self, ra, dec, jd, graceid, auth_username, auth_password, email, userpass, observing_run='O4c', path_data='data', testing=True):
        self.ra=ra
        self.dec=dec
        self.jd=jd
        self.graceid = graceid
        self.auth_username = auth_username
        self.auth_password = auth_password
        self.email = email
        self.userpass = userpass
        self.observing_run = observing_run
        self.path_data = path_data
        self.testing = testing

    def submit_post(self, ra, dec, jd):
        ra = json.dumps(ra)
        dec = json.dumps(dec)
        jdstart = json.dumps(jd)   
        jdend = json.dumps(Time.now().jd)
        payload = {'ra': ra, 'dec': dec, 'jdstart': jdstart, 'jdend': jdend, 'email': self.email, 'userpass': self.userpass}
        # fixed IP address/URL where requests are submitted:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/batchfp.py/submit'
        r = requests.post(url, auth = (self.auth_username, self.auth_password), data = payload)
        if r.status_code == 200:
            print("Success")
        else:
            print(f'Error: {r.text}')

    def save_photometry_date(self):
        photometry_date = None
        with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'r') as file:
            events_dict = json.load(file)
        if len(self.ra) == 0:
            zfps_date_dict = {self.graceid: 'NA'}  
        else:
            photometry_date = Time.now().iso    
            zfps_date_dict = {self.graceid: photometry_date}
        for key, value in zfps_date_dict.items():
            if key in events_dict:
                if 'flare' not in events_dict[key]:
                    events_dict[key]['flare'] = {}  
                events_dict[key]['flare']['date_last_zfps'] = value
                if not self.testing:  
                    with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'w') as file:
                        json.dump(events_dict, file)
            else:
                print(f'{key} not in dictionary')
        return photometry_date

    def submit(self):
        if len(self.ra) == 0:
            print('no AGN to submit')
            return None, None, None 
        elif any(isinstance(item, list) for item in self.ra):
            num_batches = len(self.ra)
            num_agn = sum([len(x) for x in self.ra])
            if self.testing:
                print('Testing mode - no submission')
            else:
                print(f'submit in {num_batches} batches')
                [self.submit_post(r, d, j) for r,d,j in zip(self.ra, self.dec, self.jd)]
        else:
            num_batches = 1
            num_agn = len(self.ra)
            if self.testing:
                print('Testing mode - no submission')
            else:
                print('submit in one batch')  
                self.submit_post(self.ra, self.dec, self.jd)         
        photometry_date = self.save_photometry_date()
        print(f'Submitted {num_agn} AGN in {num_batches} batches at {photometry_date}')
        return photometry_date, num_agn, num_batches



### functions to save and inspect photometry

class SavePhotometry():
    def __init__(self, graceid, action, path_data, batch_codes=None, submission_date=None, num_batches_submitted=None, observing_run='O4c', testing=False, email=None, userpass=None, auth_username=None, auth_password=None):
        self.graceid = graceid
        self.batch_codes = batch_codes
        self.action = action
        self.path_data = path_data
        self.submission_date = submission_date
        self.num_batches_submitted = num_batches_submitted
        self.observing_run = observing_run
        self.testing= testing
        self.email = email
        self.userpass = userpass
        self.auth_username = auth_username
        self.auth_password = auth_password
        self.path_photometry = f'{path_data}/flare_data/ZFPS/'
    
    def get_coords_batchcode(self):
        """
        load zfps table, get coords, format filename given a manually input batch code
        """
        action = 'Query Database'
        settings = {'email': self.email, 'userpass': self.userpass, 'option': 'All recent jobs', 'action': action}
        # fixed IP address/URL where requests are submitted:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/getBatchForcedPhotometryRequests.cgi'
        r = requests.get(url, auth = (self.auth_username, self.auth_password), params = settings)
        if r.status_code == 200:
            print("Script executed normally and queried the ZTF Batch Forced Photometry database.\n")
            html_content = StringIO(r.text)
            full_table = pd.read_html(html_content)[0]
            pattern = '|'.join(self.batch_codes)
            table_gw = full_table[full_table['lightcurve'].str.contains(pattern, na=False)]
            print(f'{len(table_gw)} coords found')
            ra = table_gw['ra'].tolist()
            dec = table_gw['dec'].tolist()
            name = [str(r) + '_' + str(d) for r,d in zip(ra,dec)] 
        if len(table_gw) == 0:
            return None
        return table_gw, name
    
    def get_coords_graceid(self):
        """
        load zfps table, get batch_codes, get coords, format filename given the graceid and submission date and number of batches
        """
        with gzip.open(f'{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz', 'rb') as f:
            crossmatch_dict = pickle.load(f)
        action = 'Query Database'
        settings = {'email': self.email, 'userpass': self.userpass, 'option': 'All recent jobs', 'action': action}
        # load the full table of returned zfps:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/getBatchForcedPhotometryRequests.cgi'
        r = requests.get(url, auth = (self.auth_username, self.auth_password), params = settings)
        if r.status_code != 200:
            print(f"Error: {r.status_code} - {r.text}")
            return None
        
        print("Script executed normally and queried the ZTF Batch Forced Photometry database.\n")
        html_content = StringIO(r.text)
        full_table = pd.read_html(html_content)[0]
        
        #find the coords we submitted from ra/dec
        crossmatch_df = pd.DataFrame(crossmatch_dict[self.graceid]['agn_catnorth'])
        # Deal with rounding issues and ensure consistent formatting
        def truncate_to_precision(value, precision=4):
            try:
                return f"{float(value):.{precision}f}"
            except ValueError:
                return None
        full_table['ra_truncated'] = full_table['ra'].apply(lambda x: truncate_to_precision(x))
        full_table['dec_truncated'] = full_table['dec'].apply(lambda x: truncate_to_precision(x))
        crossmatch_df['ra_truncated'] = crossmatch_df['ra'].apply(lambda x: truncate_to_precision(x))
        crossmatch_df['dec_truncated'] = crossmatch_df['dec'].apply(lambda x: truncate_to_precision(x))
        # Match ra/dec values for the event
        filtered_table = pd.merge(
            full_table,
            crossmatch_df[['ra_truncated', 'dec_truncated']],
            on=['ra_truncated', 'dec_truncated'],
            how='inner'  
        )                                                                                                                                                                        
                                                                                                                                                                    
        #find the coords from our submission date (just check close enough bc there are time zone differences)
        submission_date_astropy = Time(self.submission_date)                                                                                                                                                                                           
        def is_within_24_hours(date_str):
            date_astropy = Time(date_str)
            time_difference = abs((date_astropy - submission_date_astropy).to('hour').value)
            return time_difference <= 24
        filtered_table['matches_date'] = filtered_table['created'].apply(is_within_24_hours)
        filtered_table = filtered_table[filtered_table['matches_date']]
        filtered_table = filtered_table.drop(columns=['matches_date'])
        print(f'{len(filtered_table)} coords found')

        # check if we retrieved the same number of batches as submitted, if not, likely not complete yet
        # TODO: this will break when batch codes are > 5 digits
        def extract_batch_code(lightcurve):
            match = re.search(r'/(\d{5})/', lightcurve)
            if match:
                return match.group(1)  
            return None 
        filtered_table['batch_code'] = filtered_table['lightcurve'].apply(extract_batch_code)
        num_batches_received = filtered_table['batch_code'].nunique()
        batches_received = filtered_table['batch_code'].unique()
        print(f'Returned {num_batches_received} batches for {self.num_batches_submitted} submitted')
        if num_batches_received != self.num_batches_submitted:
            return None

        # need to do this because there is a slight difference between the coords submitted and those returned usually
        ra = filtered_table['ra'].tolist()
        dec = filtered_table['dec'].tolist()
        name = [str(r) + '_' + str(d) for r, d in zip(ra, dec)]
        return filtered_table, name, batches_received
    
    
    
    def get_photometry(self):
        """
        Check completion and return list URLs (only saved 30 days post request):
        """
        action = 'Query Database'
        settings = {'email': self.email, 'userpass': self.userpass, 'option': 'All recent jobs', 'action': action}
        # fixed IP address/URL where requests are submitted:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/getBatchForcedPhotometryRequests.cgi'
        r = requests.get(url, auth = (self.auth_username, self.auth_password), params = settings)
        if r.status_code == 200:
            print("Script executed normally and queried the ZTF Batch Forced Photometry database.\n")
            url_prefix = 'https://ztfweb.ipac.caltech.edu'
            lightcurves = re.findall(r'/ztf/ops.+?lc.txt\b', r.text)
            if lightcurves is not None:
                batch_url = [url_prefix + lc for lc in lightcurves]
            else:
                print("Status_code=",r.status_code,"; Jobs either queued or abnormal execution.")
        batch_lightcurves = [lc for lc in batch_url if any(batch in lc for batch in self.batch_codes)]
        print("Retrieved", len(batch_lightcurves), "lightcurves")
        return batch_lightcurves

    def df_from_url (self, url, file):
        """
        load lightcurves from url
        """
        data = requests.get(url, auth = (self.auth_username, self.auth_password), data = {'email': self.email, 'userpass': self.userpass})
        if data.status_code == 200:
            df=pd.read_csv(io.StringIO(data.content.decode('utf-8')), sep=r'\s+', comment='#')
            df.columns = df.columns.str.replace(',', '') 
            return df, file
    
    def quality_cut_filter (self,df):
        """
        cut down lc dfs to required columns, recommended quality filtering 
        """
        df_qf = df[(df['infobitssci'] < 33554432) & (df['scisigpix'] < 25) & (df['sciinpseeing'] < 4) & (df['forcediffimflux'] > -99998)] 
        df_qf_cut = df_qf[['dnearestrefsrc', 'zpdiff', 'nearestrefmag', 'nearestrefmagunc', 'forcediffimflux', 'forcediffimfluxunc','filter', 'jd']]
        return(df_qf_cut)

    def download_lightcurves (self, df, name):
        """
        Download lightcurve files to local directory
        """
        directory = self.path_photometry
        save_as = f"{directory}{name}.gz" 
        df.to_pickle(save_as, compression='gzip')

    def load_event_lightcurves(self, filename):
        """
        if updating existing photometry
        """
        dir = self.path_photometry
        df = [pd.read_pickle(dir + file + '.gz', compression='gzip') for file in filename if os.path.exists(dir + file + '.gz')]
        coords = [file for file in filename if os.path.exists(dir + file + '.gz')]
        return df, coords

    def save(self): 
        if self.batch_codes:
            # retrieve coords from manually input batch code
            retrieved_photometry = self.get_coords_batchcode()
        else:
            # retrieve coords directly from graceid
            retrieved_photometry = self.get_coords_graceid()
        if retrieved_photometry is None: # if not all batches are returned (could be partially returned)
            return None
        filename  = retrieved_photometry[1]
        if self.batch_codes == None:
            self.batch_codes = retrieved_photometry[2]
        lightcurves = self.get_photometry() 
        result = [self.df_from_url(url, file) for url, file in zip(lightcurves, filename)]
        errors = [x for x in result if x is None]
        num_errors = len(errors)
        values = [x for x in result if x is not None]
        print(f'{num_errors} broken urls; {len(values)} lightcurves returned')
        lc_from_url, filename_updated = zip(*values)
        lc_cut = [self.quality_cut_filter(df) for df in lc_from_url]
        # if the photometry is an update to existing photometry, open existing df and append
        if self.action == 'update':
            batch_photometry_existing, radec_existing = self.load_event_lightcurves(filename_updated)
            print(f'loaded {len(batch_photometry_existing)} existing AGN photometry for {len(lc_cut)} new AGN photometry')
            for i in range(len(batch_photometry_existing)):
                batch_photometry_existing[i] = pd.concat([batch_photometry_existing[i], lc_cut[i]]).drop_duplicates()
            if len(batch_photometry_existing) == len(filename_updated):
                if self.testing:
                    print('Testing mode - no download')
                else:
                    [self.download_lightcurves(i,j) for i,j in zip(batch_photometry_existing, filename_updated)]
                num_returned = len(batch_photometry_existing)                
            else:
                print('Error: different number of lightcurves and filenames')
                return None   
        # save the new photometry
        else:
            if len(lc_cut) == len(filename_updated):
                if self.testing:
                    print('Testing mode - no download') 
                else:
                    [self.download_lightcurves(i,j) for i,j in zip(lc_cut, filename_updated)]
                num_returned = len(lc_cut)
            else:
                print('Error: different number of lightcurves and filenames') 
                return None
        
        print(f'downloaded {num_returned} lightcurves')
        return self.batch_codes, num_returned, num_errors
            
        

class PhotometryLog():
    def __init__(self, path_data, graceid=None, column=None, value=None, new_row=None, email=None, userpass=None, auth_username=None, auth_password=None):
        self.path_data = path_data
        self.graceid = graceid
        self.column = column
        self.value = value
        self.new_row = new_row
        self.email = email
        self.userpass = userpass
        self.auth_username = auth_username
        self.auth_password = auth_password

        self.path_pipeline = f'{self.path_data}/flare_data/photometry_pipeline.json'
        with open(self.path_pipeline, 'r') as file:
            photometry_pipeline = json.load(file)
        self.photometry_pipeline = photometry_pipeline
 
    def check_completed_events(self):
        """
        check for events outside our 200 day window of observability
        """
        for id in self.photometry_pipeline['events'].keys():
            if self.photometry_pipeline['events'][id]['over_200_days'] or 'dateobs' not in self.photometry_pipeline['events'][id]:
                continue
            dateobs = self.photometry_pipeline['events'][id]['dateobs']
            if (Time.now() - Time(dateobs, format='isot')).value > 200:
                self.photometry_pipeline['events'][id]['over_200_days'] = True
                print(f'Event {id} is over 200 days old')
                with open(self.path_pipeline, 'w') as file:
                    json.dump(self.photometry_pipeline, file, indent=4)

    def update_summary_stats(self, number_requested, number_saved, keyword):
        """
        keep track of total requests and saved requests
        use pending value to prevent from having > 20,000 requests at once, which ZFPS wont allow
        """
        if keyword == 'new_request':
            self.photometry_pipeline['summary_stats']['total_requests'] += number_requested
        elif keyword == 'saved_request':
            self.photometry_pipeline['summary_stats']['total_saved'] += number_saved
        else:
            raise ValueError("Invalid keyword. Use 'new_request' or 'saved_request'.")

        with open(self.path_pipeline, 'w') as file:
            json.dump(self.photometry_pipeline, file, indent=4)

    def save_num_pending(self, num_pending):
        """
        keep track of total requests and saved requests
        use pending value to prevent from having > 20,000 requests at once, which ZFPS wont allow
        """
        self.photometry_pipeline['summary_stats']['total_currently_pending'] = num_pending
        with open(self.path_pipeline, 'w') as file:
            json.dump(self.photometry_pipeline, file, indent=4)
    
    def check_num_pending_zfps(self):
        """
        get number of pending ZFPS requests
        """
        action = 'Query Database'
        settings = {'email': self.email, 'userpass': self.userpass, 'option': 'Pending jobs', 'action': action}
        # load the full table of returned zfps:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/getBatchForcedPhotometryRequests.cgi'
        r = requests.get(url, auth = (self.auth_username, self.auth_password), params = settings)
        if r.status_code == 200:
            print("Script executed normally and queried the ZTF Batch Forced Photometry database.\n")
            html_content = StringIO(r.text)
            if "Zero records returned" in r.text:
                num_pending = 0
            else:
                full_table = pd.read_html(html_content)[0]
                num_pending= full_table.shape[0]
            print(f"Number of pending requests: {num_pending}")
            return num_pending
        elif r.status_code == 400: # unfortunately returns this error code when there are 0 pending jobs, so assume this is the case
            print("No pending jobs")
            num_pending=0
            return num_pending
        else:
            print(f"Error: {r.status_code}")
            return None

    def add_event(self, event_id, event_data):
        """
        Add a new event to the photometry pipeline.
        """
        if event_id not in self.photometry_pipeline['events']:
            self.photometry_pipeline['events'][event_id] = event_data
            try:
                num_agn = event_data['zfps']['num_agn_submitted']
            except:
                num_agn=0
            self.update_summary_stats(number_requested=num_agn,number_saved=0,keyword='new_request')
            with open(self.path_pipeline, 'w') as file:
                json.dump(self.photometry_pipeline, file, indent=4)
            print(f"Event ID {event_id} added successfully.")
        else:
            print(f"Event ID {event_id} already exists in the photometry pipeline.")

    def add_zfps_entry(self, event_id, new_entry):
        """
        Add a new entry to the zfps list for a given event ID.
        """
        if event_id in self.photometry_pipeline['events']:
            if 'zfps' not in self.photometry_pipeline['events'][event_id]:
                self.photometry_pipeline['events'][event_id]['zfps'] = []
            self.photometry_pipeline['events'][event_id]['zfps'].append(new_entry)
            num_agn = new_entry['num_agn_submitted']
            self.update_summary_stats(number_requested=num_agn,number_saved=0,keyword='new_request')
            with open(self.path_pipeline, 'w') as file:
                json.dump(self.photometry_pipeline, file, indent=4)
            print(f"New ZFPS added to {event_id}.")
        else:
            print(f"Event ID {event_id} not found in the photometry pipeline.")
    
    def check_photometry_status(self):
        """
        Check if we should request or retrieve photometry for any event
        """
        needs_photometry_request = []
        waiting_for_photometry = []
        for id in self.photometry_pipeline['events'].keys():
            if self.photometry_pipeline['events'][id]['over_200_days'] or 'dateobs' not in self.photometry_pipeline['events'][id]:
                continue
            dateobs = self.photometry_pipeline['events'][id]['dateobs']
            time_delta = round((Time.now() - Time(dateobs, format='isot')).to_value('jd'))
            # get pending photometry
            # first ZFPS request tends to take a couple days, so build in a buffer instead of hitting ZFPS daily
            if time_delta < 7:
                continue
            for x in self.photometry_pipeline['events'][id]['zfps']:
                if type(x)!= str and not x['complete']:
                    waiting_for_photometry.append([id, x['submission_date'], x['num_batches_submitted'], x['action']])
            # find events that need update photometry request based on our cadence (loosely based on followup TOO schedule)
            num_zfps_requests_so_far = len([x for x in self.photometry_pipeline['events'][id]['zfps'] if "from_queue" not in x])
            time_delta_thresholds = [9, 16, 23, 30, 52, 100]
            num_requests_should_be_made = [2, 3, 4, 5, 6, 7] # ie after 9 days, we should have 2 requests (the initial and a first update)
            if any(time_delta >= t and num_zfps_requests_so_far < z for t, z in zip(time_delta_thresholds, num_requests_should_be_made)):
                needs_photometry_request.append([id, dateobs, 'update'])
        print(f'Waiting for photometry: {[x[0] for x in waiting_for_photometry]}')
        print(f'Needs photometry request: {[x[0] for x in needs_photometry_request]}')
        return needs_photometry_request, waiting_for_photometry
    
    def update_photometry_complete(self, event_id, submission_date, batch_ids, num_returned, num_broken):
        """
        Update the photometry status for a given event ID.
        """
        if event_id in self.photometry_pipeline['events']:
            for x in self.photometry_pipeline['events'][event_id]['zfps']:
                if x['submission_date'] == submission_date:
                    x['complete'] = True
                    x['batch_ids'] = str(batch_ids)
                    x['number_returned'] = int(num_returned)
                    x['number_broken_urls'] = int(num_broken)
                    # update summary
                    num_req = x['num_agn_submitted']
                    self.update_summary_stats(number_requested=num_req,number_saved=num_returned,keyword='saved_request')
                    #save
                    with open(self.path_pipeline, 'w') as file:
                        json.dump(self.photometry_pipeline, file, indent=4)
                    print(f"Photometry status updated for {event_id}.")
                    return
            print(f"Submission date {submission_date} not found for {event_id}.")
        else:
            print(f"Event ID {event_id} not found in the photometry pipeline.")


class PlotPhotometry():
    def __init__(self, observing_run, graceid, path_data):
        self.observing_run = observing_run
        self.graceid = graceid
        self.path_data = path_data
        self.path_photometry = f'{path_data}/flare_data/ZFPS/'

    def load_event_lightcurves_graceid(self):
        # open the stored event info
        with gzip.open(f'{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz', 'rb') as f:
            crossmatch_dict = pickle.load(f)
        coords = crossmatch_dict[self.graceid]['agn_catnorth']
        name = [str(x['ra']) + '_' + str(x['dec']) for x in coords]
        dir = self.path_photometry
        df = [pd.read_pickle(dir + file + '.gz', compression='gzip') for file in name if os.path.exists(dir + file + '.gz')]
        coords = [file for file in name if os.path.exists(dir + file + '.gz')]
        return df

    def plot_photometry_dates(self):
        batch_photometry_filtered = self.load_event_lightcurves_graceid()
        empty=[x for x in batch_photometry_filtered if x.empty]
        # open the stored event info
        with open(f'{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json', 'r') as file:
            events_dict = json.load(file)
        total_matches=events_dict[self.graceid]['crossmatch']['n_agn_catnorth']
        dateobs=events_dict[self.graceid]['gw']['GW MJD']+ 2400000.5
        print(f'{len(empty)} / {len(batch_photometry_filtered)} dataframes for {total_matches} Catnorth sources are empty')
        jd_min = [x['jd'].min() for x in batch_photometry_filtered]
        jd_max = [x['jd'].max() for x in batch_photometry_filtered]
        # Create a DataFrame for plotting
        data = pd.DataFrame({
            'JD Type': ['Min'] * len(jd_min) + ['Max'] * len(jd_max),
            'JD Value': jd_min + jd_max
        })
        # Create the violin plot
        plt.figure(figsize=(10, 6))
        sns.violinplot(x='JD Type', y='JD Value', data=data)
        plt.title('Distribution of JD Minimum and Maximum Values')
        plt.xlabel('Min and Max photometry values')
        plt.ylabel('JD')
        # Add a horizontal line labeled "GW"
        plt.axhline(y=dateobs, color='r', linestyle='--')
        plt.text(0.4, dateobs, 'GW', color='r', ha='center', va='bottom')
        plt.axhline(y=dateobs - 2*360, color='b', linestyle='--')
        plt.text(0.5, dateobs - 2*360, 'Baseline', color='b', ha='center', va='bottom')
        current_jd = Time.now().jd
        plt.axhline(y=current_jd, color='g', linestyle='--')
        plt.text(0.6, current_jd, 'Now', color='g', ha='center', va='bottom')
        plt.show()