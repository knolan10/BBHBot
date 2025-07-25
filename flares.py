import yaml
from astropy.time import Time

from flares_utils.new_events_utils import (
    GetSuperevents,
    Fritz,
    NewEventsToDict,
    KowalskiCrossmatch,
    PushEventsPublic,
)
from flares_utils.photometry_utils import (
    PhotometryLog,
    PhotometryCoords,
    GetPhotometry,
    SavePhotometry,
)
from flares_utils.flares_utils import (
    FlarePreprocessing,
    RollingWindowStats,
    RollingWindowHeuristic,
)
from utils.log import Logger
from utils.parser import followup_parser_args


class MyException(Exception):
    pass


# settings for flares bot
args = followup_parser_args()
testing = args.testing
path_data = args.path_data
observing_run = args.observing_run

# credentials
with open("config/Credentials.yaml", "r") as file:
    credentials = yaml.safe_load(file)
zfps_email = credentials["zfps_email"]
zfps_userpass = credentials["zfps_userpass"]
zfps_auth_username = credentials["zfps_auth"]["username"]
zfps_auth_password = credentials["zfps_auth"]["password"]
allocation = credentials["allocation"]
fritz_token = credentials["fritz_token"]
kowalski_username = credentials["kowalski_username"]
kowalski_password = credentials["kowalski_password"]
github_token = credentials["github_token"]

# set up logging that writes messages locally, sends to slack, and sends emails
if testing:
    webhook = credentials["slack_webhook_testing"]
else:
    webhook = credentials["slack_webhook"]

logger = Logger(webhook, filename="flares")

logmessage = f"Starting flares.py at at {Time.now()} with testing = {testing}"
logger.log(logmessage)

# Part 0 : load current photometry status
logger.log("PART 0: Check status, try to submit queued requests")
do_photometry = (
    True  # this flag will be changed to false if we hit the 15000 request limit
)

followup = PhotometryLog(
    path_data,
    email=zfps_email,
    userpass=zfps_userpass,
    auth_username=zfps_auth_username,
    auth_password=zfps_auth_password,
)
followup.check_completed_events()  # if events are out of 200 day window, edit log so we stop checking them
# action items :
needs_photometry_request, waiting_for_photometry = followup.check_photometry_status()
number_pending_requests = followup.check_num_pending_zfps()
if number_pending_requests > 15000:  # ZFPS limit
    do_photometry = False

# check for queued photometry requests (if we previously hit the 15000 limit)
# if not testing and do_photometry:
if do_photometry:
    queued_photometry = PhotometryCoords.retrieve_queue_photometry(path_data)
    if len(queued_photometry) > 0:
        (f"Found {len(queued_photometry)} queued photometry requests")
        for x in queued_photometry:
            id = x[0]
            ra = x[1]
            dec = x[2]
            jd = x[3]
            number_to_submit = x[4]
            action = x[5]
            file_name = x[6]
            if number_pending_requests + number_to_submit > 15000:
                do_photometry = False
                logger.log(
                    f"Not submitting queued request for {id} - still too many pending"
                )
                break
            logger.log(
                f"Submitting {number_to_submit} queued photometry coords for event {id}"
            )

            submission = GetPhotometry(
                ra,
                dec,
                jd,
                id,
                zfps_auth_username,
                zfps_auth_password,
                zfps_email,
                zfps_userpass,
                observing_run=observing_run,
                path_data=path_data,
                testing=testing,
            ).submit()

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
                    "complete": False,
                    "from_queue": True,
                }
                followup.add_zfps_entry(event_id=id, new_entry=new_zfps_entry)
                number_pending_requests += submission[1]
                # move the file of queued photometry into another "completed queued" directory - could periodically delete these
                PhotometryCoords.move_complete_queued_photometry(file_name, path_data)
                logger.log(f"Completed queued photometry submission for {id}")
            else:
                logger.log(f"Error submitting queued photometry for {id}")

###Part 1 : injest new events, and along with scheduled updates, request photometry
logger.log("PART 1: Photometry Requests")

# check gracedb for new events
params = GetSuperevents(
    path_data=path_data, event_source="gracedb", observing_run=observing_run
).get_new_events()
logger.log(f"found {len(params)} new events")

# check the trigger status of new events on Fritz
eventid = [x[0] for x in params]
far = [x[9] for x in params]
dateobs = [x[11] for x in params]
dateid = [x[12] for x in params]
a90 = [x[16] for x in params]
mass = [x[22] for x in params]
trigger_status = Fritz(
    eventid,
    dateid,
    a90,
    far,
    mass,
    allocation,
    fritz_token,
    kowalski_username,
    kowalski_password,
).get_trigger_status()

# save the new events to dictionary
df = NewEventsToDict(
    params, trigger_status, path_data, observing_run, testing
).save_data()

# get catnorth crossmatches
skymap_str = [x[18] for x in params]
zmin = [x[19] for x in params]
zmax = [x[20] for x in params]
crossmatch = KowalskiCrossmatch(
    eventid,
    skymap_str,
    dateid,
    zmin,
    zmax,
    path_data,
    observing_run,
    testing=testing,
    kowalski_username=kowalski_username,
    kowalski_password=kowalski_password,
)
matches = crossmatch.get_crossmatches()

# compile all this info in events_summary directory
df, priority, trigger_df, error_triggers = PushEventsPublic(
    path_data, github_token, observing_run=observing_run, testing=testing
).format_and_push()

# get triggered events for automatated photometry request
for id, date, trigger in zip(eventid, dateobs, trigger_status):
    zfps = None
    if trigger[0] == "correct" and trigger[1] != "triggered":
        logger.log(f"no trigger, so not ZFPS request for {id}")
        continue
    if trigger[0] != "correct" or trigger[1] != "triggered":
        logger.log(f"need to inspect event {id} for trigger status: {trigger}")
        zfps = "did not make new request"
    time_since_event = Time.now().jd - Time(date).jd
    if (
        time_since_event > 30
    ):  # safeguard: don't automatically request if more than a week has passed
        logger.log(
            f"Not automatically requesting photometry for event {id} because it has been more than 7 days"
        )
        zfps = "missed new request"
    if zfps:
        # save these failed automatic ZFPS for inspection
        event_data = {"dateobs": date, "over_200_days": False, "zfps": [zfps]}
        followup.add_event(id, event_data)
        logger.log(f"Found event {id} to request new photometry for")
        continue
    # events that have made it this far need new photometry request, we append them to any update requests scheduled
    needs_photometry_request.append([id, date, "new"])

# for triggered events, request the baseline forced photometry for all AGN with no locally save photometry
# for update events, update photometry for all locally saved AGN
for x in needs_photometry_request:
    id, date, action = x[0], x[1], x[2]
    logger.log(f"Submitting {action} photometry request for event {id}")
    coords = PhotometryCoords(
        action=action,
        graceid=id,
        catalog="catnorth",
        verbose=True,
        path_data=path_data,
        observing_run=observing_run,
    )

    ra, dec, jd, number_agn = coords.get_photometry_coords()

    # make sure we are within photometry limit
    # TODO : could optimize this more so we always have the max number of requests in at any given time
    if number_pending_requests + number_agn > 15000:
        event_data = {"dateobs": date, "over_200_days": False, "zfps": []}
        followup.add_event(id, event_data)
        coords.queue_photometry(ra, dec, jd, number_agn)
        logger.log(
            f"Not submitting {action} photometry request for event {id} - too many pending requests"
        )
        do_photometry = False
        continue

    submission = GetPhotometry(
        ra,
        dec,
        jd,
        id,
        zfps_auth_username,
        zfps_auth_password,
        zfps_email,
        zfps_userpass,
        observing_run=observing_run,
        path_data=path_data,
        testing=testing,
    ).submit()

    new_zfps_entry = {
        "catalog": "catnorth",
        "submission_date": submission[0],
        "action": action,
        "num_agn_submitted": submission[1],
        "num_batches_submitted": submission[2],
        "batch_ids": None,
        "number_returned": None,
        "number_broken_urls": None,
        "complete": False,
    }

    number_pending_requests += number_agn

    # save this event
    event_data = {"dateobs": date, "over_200_days": False, "zfps": []}
    followup.add_event(id, event_data)
    followup.add_zfps_entry(event_id=id, new_entry=new_zfps_entry)

# save number of updated pending requests
followup.save_num_pending(number_pending_requests)

# PART 2 : address waiting_for_photometry
logger.log("PART 2: Retrieve Photometry")
logger.log(f"Checking {len(waiting_for_photometry)} photometry requests")
check_for_flares = []
for x in waiting_for_photometry:
    id, date_submitted, num_batches, action = x[0], x[1], x[2], x[3]
    logger.log(
        f"Now checking {num_batches} batches {action} request for event {id} on {date_submitted}"
    )
    save_photometry = SavePhotometry(
        graceid=id,
        action=action,
        path_data=path_data,
        submission_date=date_submitted,
        num_batches_submitted=num_batches,
        observing_run=observing_run,
        testing=testing,
        email=zfps_email,
        userpass=zfps_userpass,
        auth_username=zfps_auth_username,
        auth_password=zfps_auth_password,
    )
    saved = save_photometry.save()
    if saved:  # if we don't return the number of batches submitted, we will try again the next day
        # make a log of the photometry that was returned
        batch_ids = saved[0]
        num_returned = saved[1]
        num_broken_urls = saved[2]
        followup.update_photometry_complete(
            id, date_submitted, batch_ids, num_returned, num_broken_urls
        )
        # save id to run flare analysis in the next step
        check_for_flares.append(id)


logger.log("PART 3: Flare identification")
check_for_flares = list(set(check_for_flares))
if len(check_for_flares) == 0:
    logger.log("No new photometry to check for flares")
for id in check_for_flares:
    # check for flares (will overwrite previouse flare checks each time)
    AGN = FlarePreprocessing(
        graceid=id, path_data=path_data, observing_run=observing_run
    ).process_for_flare()
    rolling_stats = RollingWindowStats(
        graceid=id, agn=AGN, path_data=path_data, observing_run=observing_run
    ).get_rolling_window_stats()
    g, r, i, gr, gri = RollingWindowHeuristic(
        graceid=id,
        agn=AGN,
        rolling_stats=rolling_stats,
        path_data=path_data,
        observing_run=observing_run,
        percent=0.6,
        k_mad=3,
        testing=testing,
    ).get_flares()
