# this will run once a day to check for tasks
from new_events_utils import *
from photometry_utils import *
from flares_utils import *

class MyException(Exception):
    pass

# local path variables
path_events_dictionary = 'data/' 
path_queued_photometry = 'data/queued_for_photometry/'
path_photometry = '../../../../data/bbh/ZFPS/'
mlp_modelpath = 'mlp_model.sav' 
path_photometry_pipeline = 'data/photometry_pipeline.csv'
# mode (testing means don't push results, dont request forced photometry)
testing = True  
do_photometry = True # this flag will be changed to false if we hit the 15000 request limit

###PART 1 : check flare_pipeline for pending tasks
followup = PhotometryLog(path_photometry_pipeline)
followup.check_completed_events()
first_update, update, pending = followup.check_photometry_status()
number_pending_requests = followup.check_number_pending()
if number_pending_requests > 15000:
    do_photometry = False

# retrieve new photometry results for events that are 9 days in
save_photometry = SavePhotometry(path_photometry=path_photometry)
for x in first_update:
    id, date_submitted, num_batches = x[0], x[1], x[2]
    saved = save_photometry.save(graceid=id, action='new', submission_date=date_submitted, num_batches_submitted=num_batches)
    if saved:
        batch_ids = saved[0]
        num_returned = saved[1]
        num_broken_urls = saved[2]
        followup.update_photometry_complete(id, date_submitted, batch_ids, num_returned, num_broken_urls)

# check for queued photometry requests (if we previously hit the 15000 limit)
if not testing and do_photometry:
    queued_photometry = PhotometryCoords.retrieve_queue_photometry(path_queued_photometry)
    if len(queued_photometry) > 0:
        for x in queued_photometry:
            id = x[0]
            ra = x[1]
            dec = x[2]
            jd = x[3]
            action = x[4]
            number_to_submit = x[4]
            if number_pending_requests + number_to_submit > 15000:
                do_photometry = False
                break
            submission = GetPhotometry(graceid=id,
                        ra=ra,
                        dec=dec,
                        jd=jd).submit()
            if submission:
                new_zfps_entry = {
                    "catalog": "catnorth",
                    "submission_date": submission[0],
                    "action": action,
                    "num_agn_submitted": submission[1],
                    "num_batches_submitted": submission[2],
                    "batch_ids": None,
                    "number_returned": None,
                    "number_broken_urls": None,
                    "complete": False
                }
                update_followup = followup.add_zfps_entry(event_id=id, 
                                                        new_entry=new_zfps_entry)
                number_pending_requests += submission[1]
            else:
                print("Error submitting queued photometry")

# submit request for update photometry 9, 20, 30, 50, 100 days in
first_update_ids = [x[0] for x in first_update]
for x in update + first_update_ids:
    ra, dec, jd, number_agn = PhotometryCoords(action='update', 
                            graceid=x, 
                            catalog='catnorth', 
                            verbose=True,
                            path_events_dictionary=path_events_dictionary,
                            path_photometry=path_photometry).get_photometry_coords()
    
    #make sure we are within photometry limit
    if number_pending_requests + number_agn > 15000:
        PhotometryCoords.queue_photometry(x, ra, dec, jd, number_agn, 'update', path_queued_photometry)
        do_photometry = False
        continue

    submission = GetPhotometry(graceid=x,
                ra=ra,
                dec=dec,
                jd=jd).submit()
    
    if submission:
        new_zfps_entry = {
            "catalog": "catnorth",
            "submission_date": submission[0],
            "action": "update",
            "num_agn_submitted": submission[1],
            "num_batches_submitted": submission[2],
            "batch_ids": None,
            "number_returned": None,
            "number_broken_urls": None,
            "complete": False
        }
        update_followup = followup.add_zfps_entry(event_id=x, 
                                                    new_entry=new_zfps_entry)
        number_pending_requests += submission[1]

# check if requested update photometry has returned
for x in pending:
    id = x[0]
    submission_date = x[1]
    num_batches_submitted = x[2]
    saved = save_photometry.save(graceid=id, 
                                 action='update', 
                                 submission_date=submission_date, 
                                 num_batches_submitted=num_batches_submitted)
    
    if saved:
        batch_ids = saved[0]
        num_returned = saved[1]
        num_broken_urls = saved[2]
        followup.update_photometry_complete(id, date_submitted, batch_ids, num_returned, num_broken_urls)
        
        # check for flares (will overwrite previouse flare checks each time)
        AGN = FlarePreprocessing(graceid=id, 
                                path_events_dictionary=path_events_dictionary, 
                                path_photometry=path_photometry).process_for_flare()
        rolling_stats = RollingWindowStats(graceid=id, 
                                agn=AGN, 
                                path_events_dictionary=path_events_dictionary).get_rolling_window_stats()
        g, r, i, gr, gri = RollingWindowHeuristic(graceid=id, 
                                            agn=AGN, 
                                            rolling_stats=rolling_stats, 
                                            path_events_dictionary=path_events_dictionary,
                                            percent=0.6, 
                                            k_mad=3, 
                                            save=True).get_flares()

###Part 2 : injest new events

#check gracedb for new events
params = GetSuperevents(path_events_dictionary='bot/data', 
                        mlp_modelpath='bot/mlp_model.sav',
                        event_source='gracedb').get_new_events()

#check the trigger status on Fritz
eventid = [x[0] for x in params]
dateobs = [x[11] for x in params]
dateid = [x[12] for x in params]
a90 = [x[16] for x in params]
far = [x[9] for x in params]
mass = [x[22] for x in params]
trigger_status = Fritz(eventid, dateid, a90, far, mass).get_trigger_status()

#save the new events to dictionary
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

for id, date in zip(eventid, dateobs):
    # request the baseline forced photometry for all AGN with no locally save photometry
    ra, dec, jd, number_agn = PhotometryCoords(action='new', 
                                graceid=id, 
                                catalog='catnorth', 
                                verbose=True,
                                path_events_dictionary=path_events_dictionary,
                                path_photometry=path_photometry).get_photometry_coords()

    time_since_event = Time.now().jd - Time(dateobs).jd
    if testing or time_since_event > 7: # safeguard: don't automatically request if more than a week has passed
        print(f"Not automatically requesting photometry for event {id} because it has been more than 7 days")
        zfps = "missed new request"

    else:
        #make sure we are within photometry limit
        if number_pending_requests + number_agn > 15000:
            PhotometryCoords.queue_photometry(id, ra, dec, jd, number_agn, 'new', path_queued_photometry)
            do_photometry = False
            continue
            
        submission = GetPhotometry(graceid=id,
                    ra=ra,
                    dec=dec,
                    jd=jd).submit()
        zfps = {
                "catalog": "catnorth",
                "submission_date": submission[0],
                "action": "new",
                "num_agn_submitted": submission[1],
                "num_batches_submitted": submission[2],
                "batch_ids": None,
                "number_returned": None,
                "number_broken_urls": None,
                "complete": False
            }
        
        number_pending_requests += number_agn

    # save this event to data/photometry_pipeline.json
    event_data = {
        "dateobs": date,
        "over_200_days": False,
        "zfps": [
            zfps
        ]
    }
    followup.add_event(eventid, event_data)