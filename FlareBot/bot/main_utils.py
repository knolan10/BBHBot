import pandas as pd
from astropy.time import Time

class FlareFollowup():
    def __init__(self, path_pipeline, graceid=None, column=None, value=None, new_row=None):
        self.path_pipeline = path_pipeline
        self.df = pd.read_csv(path_pipeline)
        self.graceid = graceid
        self.column = column
        self.value = value
        self.new_row = new_row
 
    def check_completed_events(self):
        """
        check for events outside our 200 day window of observability
        """
        for row in self.df.itertuples(index=False):
            dateobs = row.dateobs
            # if dateobs is more than 200 days ago, update row.over_200_days to True
            if (Time.now() - Time(dateobs, format='isot')).value > 200:
                self.df.loc[self.df.dateobs == dateobs, 'over_200_days'] = True
        self.df.to_csv('bot/data/flare_pipeline.csv', index=False)
    
    def check_photometry_request(self):
        """
        Check if we have pending observations
        """
        pending_request = []
        update_request = []
        first_update_request = []
        for row in self.df.itertuples(index=False):
            if row.over_200_days:
                continue
            if row.waiting_for_update_photometry:
                pending_request.append(row.eventid)
            time_delta = round((Time.now() - Time(self.df.dateobs[0], format='isot')).to_value('jd'))
            if time_delta == 9:
                first_update_request.append(row.eventid)
            if time_delta in [20, 30, 50, 100]:
                update_request.append(row.eventid)
        print(f'Pending request: {pending_request}')
        print(f'Update request: {update_request}')
        return first_update_request, update_request, pending_request

    def edit_csv(self):
        """
        Edit a csv file
        """
        self.df.loc[self.df.eventid == self.graceid, self.column] = self.value
        self.df.to_csv('bot/data/flare_pipeline.csv', index=False)

    def append_row_csv(self):
        """
        Append a row to a csv file
        """
        self.df = self.df.append(self.new_row, ignore_index=True)
        self.df.to_csv('bot/data/flare_pipeline.csv', index=False)  