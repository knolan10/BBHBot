# this will run once a day to check for tasks
from new_events_utils import *
from photometry_utils import *
from flares_utils import *
from main_utils import FlareFollowup

class MyException(Exception):
    pass

# local path variables
path_events_dictionary = 'data/' 
path_photometry = '../../../../data/bbh/ZFPS/'
mlp_modelpath = 'mlp_model.sav' 
path_flare_pipeline = 'data/flare_pipeline.csv'
# mode (testing means don't save or push findings)
testing = True  

###PART 1 : check flare_pipeline for pending tasks
followup = FlareFollowup(path_flare_pipeline)
followup.check_completed_events()
first_update, update, pending = followup.check_photometry_request()
# handle events that are 9 days in, ie first flare check
for x in first_update:
    # INSERT FUNCTION TO SAVE NEW PHOTOMETRY
    # change table date_last_photometry value
    pass


# update photometry 9, 20, 30, 50, 100 days in
for x in update + first_update:
    ra, dec, jd = PhotometryCoords(action='update', 
                            graceid=x, 
                            catalog='catnorth', 
                            verbose=True,
                            path_events_dictionary=path_events_dictionary,
                            path_photometry=path_photometry).get_photometry_coords()

    GetPhotometry(graceid=x,
                ra=ra,
                dec=dec,
                jd=jd)
    
    update_followup = FlareFollowup(path_flare_pipeline, 
                                    graceid=x, 
                                    column='waiting_for_update_photometry', value=True).edit_csv()

# check if requested photometry has returned
for x in pending:
    # INSERT FUNCTION TO CHECK IF PHOTOMETRY HAS RETURNED
    # change table waiting_for_update_photometry to False (bug - if update has been requested multiple times)
    batch_codes = []

    # when update photometry has returned, save the updated photometry, check for flares
    SavePhotometry(graceid=x, 
                batch_codes=batch_codes, 
                action='update', 
                path_photometry=path_photometry).save_photometry()
    
    # check for flares (will overwrite previouse flare checks each time)
    AGN = FlarePreprocessing(graceid=x, 
                            path_events_dictionary=path_events_dictionary, 
                            path_photometry=path_photometry).process_for_flare()
    rolling_stats = RollingWindowStats(graceid='S241114y', 
                               agn=AGN, 
                               path_events_dictionary=path_events_dictionary).get_rolling_window_stats()
    g, r, i, gr, gri = RollingWindowHeuristic(graceid=x, 
                                          agn=AGN, 
                                          rolling_stats=rolling_stats, 
                                          path_events_dictionary=path_events_dictionary,
                                          percent=0.6, 
                                          k_mad=3, 
                                          save=True).get_flares()

###Part 2 : 

#check gracedb for new events
params = GetSuperevents(path_events_dictionary='bot/data', 
                        mlp_modelpath='bot/mlp_model.sav',
                        event_source='gracedb').get_new_events()

#check the trigger status on Fritz
eventid = [x[0] for x in params]
dateid = [x[12] for x in params]
a90 = [x[16] for x in params]
far = [x[9] for x in params]
mass = [x[22] for x in params]
trigger_status = Fritz(eventid, dateid, a90, far, mass).get_trigger_status()

#save the new events to dictionary
if not testing: 
    df = NewEventsToDict(params, 
                        trigger_status, 
                        path_events_dictionary).save_data()

#get catnorth crossmatches
skymap_str = [x[18] for x in params]
zmin = [x[19] for x in params]
zmax = [x[20] for x in params]
crossmatch = KowalskiCrossmatch(eventid, 
                                skymap_str, 
                                dateid, 
                                zmin, 
                                zmax, 
                                path_events_dictionary,
                                testing=testing)
matches = crossmatch.get_crossmatches()

#compile all this info in events_summary directory
df, priority, trigger_df, error_triggers = PushEventsPublic(path_events_dictionary,
                                                            testing=testing, 
                                                            verbose=True).format_and_push()

# request the baseline forced photometry for all new AGN
ra, dec, jd = PhotometryCoords(action='new', 
                            graceid=eventid, 
                            catalog='catnorth', 
                            verbose=True,
                            path_events_dictionary=path_events_dictionary,
                            path_photometry=path_photometry).get_photometry_coords()

GetPhotometry(graceid=eventid,
              ra=ra,
              dec=dec,
              jd=jd)

# save this event to data/pipeline.csv for further analysis
new_row = {'eventid': eventid, 'dateobs': dateid, 'over_200_days': False, 'waiting_for_update_photometry': False}
followup = FlareFollowup(path_flare_pipeline, new_row=new_row).append_row_csv()


