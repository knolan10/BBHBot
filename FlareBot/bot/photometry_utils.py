import yaml
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

#credentials
with open('bot/FlareBotCredentials.yaml', 'r') as file:
    credentials = yaml.safe_load(file)
email = credentials['zfps_email']
userpass = credentials['zfps_userpass']
auth_username = credentials['zfps_auth']['username']
auth_password = credentials['zfps_auth']['password']

class PhotometryStatus:
    def __init__(self, observing_run, path_events_dictionary):
        self.observing_run = observing_run
        self.path_events_dictionary = path_events_dictionary    

    def show_status(self):
        try:
            with open(f'{self.path_events_dictionary}/dicts/events_dict_{self.observing_run}.json', 'r') as file:
                events_dict = json.load(file)
        except:
            print('observing_run must be O4a or O4b')
            return
        # make this automatic
        trigger_list = ['S240919bn', 'S240923ct', 'S241006k', 'S241009em', 'S241114y']
        good_events = [key for key, value in events_dict.items() if value['gw']['Mass (M_sol)'] > 60 
                    and value['gw']['90% Area (deg2)'] < 1000
                    and value['gw']['FAR (years/FA)'] > 10]
        print(f'{len(events_dict) - len(good_events)} / {len(events_dict)} events in O4b are not priority')
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
    def __init__(self, action, graceid, catalog, verbose, path_events_dictionary, path_photometry):
        self.action = action
        self.graceid = graceid
        self.catalog = catalog
        self.verbose = verbose
        self.path_events_dictionary = path_events_dictionary
        self.path_photometry = path_photometry

    def get_agn_coords(self):
        """"
        get AGN coords for a given event
        Depending on action variable, will get all coords, only coords we have no photometry, or coords and dates to update photometry
        input: graceid (string), catalog (list of string names of catalogs), action ('all', 'new', 'update') 
        """
        # open the stored event info
        with gzip.open(f'{self.path_events_dictionary}/dicts/crossmatch_dict_O4b.gz', 'rb') as f:
            crossmatch_dict = pickle.load(f)
        with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
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
            print (f'about {len(ztf_coords)} / {len(all_coords)} coords should be in ZTF footprint')
            return ztf_coords, two_year_baseline
        names = [str(x['ra']) + '_' + str(x['dec']) for x in ztf_coords]
        path = self.path_photometry #path to where photometry is stored locally
        if self.action == 'new':
            new_coords = [coords for coords,name in zip(ztf_coords, names) if not os.path.exists(path + name + '.gz')]
            print (f'{len(new_coords)} / {len(all_coords)} total coords dont have photometry')
            return new_coords, two_year_baseline
        if self.action == 'update':
            if events_dict[self.graceid]['flare']:
                date_zfps = events_dict[self.graceid]['flare']['date_last_zfps'] 
                print(f'last photometry request for {self.graceid} was on {date_zfps}')
            else:
                print(f'Error: no photometry for {self.graceid}')  
                return
            existing_coords = [coords for coords,name in zip(ztf_coords, names) if os.path.exists(path + name + '.gz')]
            print (f'Found saved photometry for {len(existing_coords)} / {len(all_coords)} coords crossmatched')
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
        ZFPS cant take multiple dates for batched requests, so batch ourselves
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
        with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
            events_dict = json.load(file)
        ra = [val['ra'] for val in coords]
        dec = [val['dec'] for val in coords]
        if len(coords) > 15000:
            print('More than 15000 AGN - over maximum submissions allowed at one time')   
            return
        elif len(coords) == 0:   
            print('no AGN to submit')
            events_dict[self.graceid]['flare'] = {'date_last_zfps': 'no AGN observable by ZTF'}
            with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'w') as file:
                json.dump(events_dict, file) 
            return
        elif len(coords) <= 1500:
            if self.verbose:
                print('Fewer than 1500 AGN - submit in one batch')
            return ra, dec, date
        # submit in multiple batches when >1500 objects
        elif len(coords) > 1500:
            ralist = [ra[i:i+1500] for i in range(0, len(ra), 1500)]
            declist = [dec[i:i+1500] for i in range(0, len(dec), 1500)]
            if self.action == 'update':
                date = [date] * len(ralist)
            print(f'More than 1500 AGN - submit in {len(ralist)} batches')
            return ralist, declist, date
        
    def replace_scientific_notation(self, ra_list, dec_list):
        """
        sometimes coords are formatted in scientific notation, which ZFPS can't handle
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
        ra,dec = self.replace_scientific_notation(ra, dec)
        return ra, dec, jd
    


class GetPhotometry():
    def __init__(self, graceid, ra, dec, jd, path_events_dictionary):
        self.graceid = graceid
        self.ra = ra
        self.dec = dec
        self.jd = jd
        self.path_events_dictionary = path_events_dictionary

    def submit_post(self):
        ra = json.dumps(self.ra)
        dec = json.dumps(self.dec)
        jdstart = json.dumps(self.jd)   
        jdend = json.dumps(Time.now().jd)
        payload = {'ra': ra, 'dec': dec, 'jdstart': jdstart, 'jdend': jdend, 'email': email, 'userpass': userpass}
        # fixed IP address/URL where requests are submitted:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/batchfp.py/submit'
        r = requests.post(url, auth = (auth_username, auth_password), data = payload)
        if r.status_code == 200:
            print("Success")
        else:
            print(f'Error: {r.text}')

    def save_photometry_date(self):

        if len(self.ra) == 0:
            zfps_date_dict = {self.graceid: 'NA'}  
        else:    
            zfps_date_dict = {self.graceid: Time.now().iso}  
        for key, value in zfps_date_dict.items():
            if key in events_dict:
                if 'flare' not in events_dict[key]:
                    events_dict[key]['flare'] = {}  
                events_dict[key]['flare']['date_last_zfps'] = value
                with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'w') as file:
                    json.dump(events_dict, file)
            else:
                print(f'{key} not in dictionary')

    def submit(self):
        if len(self.ra) == 0:
            print('no AGN to submit')
        elif any(isinstance(item, list) for item in self.ra):
            print(f'submit in {len(self.ra)} batches')
            [self.submit_post(r, d, j) for r,d,j in zip(self.ra, self.dec, self.jd)]
        else:
            print('submit in one batch')           
            self.submit_post()
        self.save_photometry_date()




class SavePhotometry():
    def __init__(self, graceid, batch_codes, action, path_photometry):
        self.graceid = graceid
        self.batch_codes = batch_codes
        self.action = action
        self.path_photometry = path_photometry

    def get_photometry(self):
        """
        Check completion and return list URLs (only saved 30 days post request):
        """
        action = 'Query Database'
        settings = {'email': email, 'userpass': userpass, 'option': 'All recent jobs', 'action': action}
        # fixed IP address/URL where requests are submitted:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/getBatchForcedPhotometryRequests.cgi'
        r = requests.get(url, auth = (auth_username, auth_password), params = settings)
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
    
    def get_coords(self):
        """
        load zfps table, get coords, format filename
        """
        action = 'Query Database'
        settings = {'email': email, 'userpass': userpass, 'option': 'All recent jobs', 'action': action}
        # fixed IP address/URL where requests are submitted:
        url = 'https://ztfweb.ipac.caltech.edu/cgi-bin/getBatchForcedPhotometryRequests.cgi'
        r = requests.get(url, auth = (auth_username, auth_password), params = settings)
        if r.status_code == 200:
            print("Script executed normally and queried the ZTF Batch Forced Photometry database.\n")
            html_content = StringIO(r.text)
            full_table = pd.read_html(html_content)[0]
            pattern = '|'.join(self.batch_codes)
            table_gw = full_table[full_table['lightcurve'].str.contains(pattern, na=False)]
            print (len(table_gw), 'coords found')
            ra = table_gw['ra'].tolist()
            dec = table_gw['dec'].tolist()
            name = [str(r) + '_' + str(d) for r,d in zip(ra,dec)] 
        return table_gw, name

    def df_from_url (url, file):
        """
        load lightcurves from url
        """
        data = requests.get(url, auth = (auth_username, auth_password), data = {'email': email, 'userpass': userpass})
        if data.status_code == 200:
            df=pd.read_csv(io.StringIO(data.content.decode('utf-8')), sep=r'\s+', comment='#')
            df.columns = df.columns.str.replace(',', '') 
            return df, file
    
    def quality_cut_filter (df):
        """
        cut down lc dfs to required columns, recommended quality filtering 
        """
        df_qf = df[(df['infobitssci'] < 33554432) & (df['scisigpix'] < 25) & (df['sciinpseeing'] < 4) & (df['forcediffimflux'] > -99998)] 
        df_qf_cut = df_qf[['dnearestrefsrc', 'zpdiff', 'nearestrefmag', 'nearestrefmagunc', 'forcediffimflux', 'forcediffimfluxunc','filter', 'jd']]
        return(df_qf_cut)

    def download_lightcurves (df, name):
        """
        Download lightcurve files to local directory
        """
        directory = self.path_photometry
        save_as = f"{directory}{name}.gz" 
        df.to_pickle(save_as, compression='gzip')

    def load_event_lightcurves(filename):
        """
        if updating existing photometry
        """
        dir = self.path_photometry
        df = [pd.read_pickle(dir + file + '.gz', compression='gzip') for file in filename if os.path.exists(dir + file + '.gz')]
        coords = [file for file in filename if os.path.exists(dir + file + '.gz')]
        return df, coords

    def get_batch_photometry(self): 
        lightcurves = self.get_photometry() 
        table, filename = self.get_coords()
        result = [self.df_from_url(url, file) for url, file in zip(lightcurves, filename)]
        errors = [x for x in result if x is None]
        values = [x for x in result if x is not None]
        print (len(errors), 'broken urls;', len(values), 'lightcurves returned')
        lc_from_url, filename_updated = zip(*values)
        lc_cut = [self.quality_cut_filter(df) for df in lc_from_url]
        # if the photometry is an update to existing photometry, open existing df and append
        if self.action == 'update':
            batch_photometry_existing, radec_existing = self.load_event_lightcurves(filename_updated)
            print(f'loaded {len(batch_photometry_existing)} existing AGN photometry for {len(lc_cut)} new AGN photometry')
            for i in range(len(batch_photometry_existing)):
                batch_photometry_existing[i] = pd.concat([batch_photometry_existing[i], lc_cut[i]]).drop_duplicates()
            if len(batch_photometry_existing) == len(filename_updated):
                [self.download_lightcurves(i,j) for i,j in zip(batch_photometry_existing, filename_updated)]
                print('downloaded', len(batch_photometry_existing), 'lightcurves')
            else:
                print('Error: different number of lightcurves and filenames')   
        # save the new photometry
        else:
            if len(lc_cut) == len(filename_updated):
                [self.download_lightcurves(i,j) for i,j in zip(lc_cut, filename_updated)]
                print('downloaded', len(lc_cut), 'lightcurves')
            else:
                print('Error: different number of lightcurves and filenames')  



class PlotPhotometry():
    def __init__(self, graceid, path_events_dictionary, path_photometry):
        self.graceid = graceid
        self.path_events_dictionary = path_events_dictionary
        self.path_photometry = path_photometry

    def load_event_lightcurves_graceid(self):
        # open the stored event info
        with gzip.open(f'{self.path_events_dictionary}/dicts/crossmatch_dict_O4b.gz', 'rb') as f:
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
        with open(f'{self.path_events_dictionary}/dicts/events_dict_O4b.json', 'r') as file:
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