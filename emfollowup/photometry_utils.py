import yaml
import pickle
import gzip
import json
import pandas as pd
from datetime import datetime

with open('../credentials.yaml', 'r') as file:
    credentials = yaml.safe_load(file)

# github_token = credentials['github_token']
# kowalski_token = credentials['kowalski_token']
# kowalski_password = credentials['kowalski_password']
# email = credentials['zfps_email']
# userpass = credentials['zfps_userpass']
# zfps_auth = credentials['zfps_auth']


# with gzip.open('dicts/crossmatch_dict_O4b.gz', 'rb') as f:
#     crossmatch_dict = pickle.load(f)

# with open('dicts/events_dict_O4b.json', 'r') as file:
#     events_dict = json.load(file)

class PhotometryStatus:
    def __init__(self, observing_run):
        self.observing_run = observing_run

    def show_status(self):
        if self.observing_run == 'O4b':
            with open('./dicts/events_dict_O4b.json', 'r') as file:
                events_dict = json.load(file)
        elif self.observing_run == 'O4a':
            with open('./dicts/events_dict_O4a.json', 'r') as file:
                events_dict = json.load(file)
        else:
            print('observing_run must be O4a or O4b')
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
