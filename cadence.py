from trigger_utils.cadence_utils import (
    parse_pending_observation,
    trigger_on_cadence,
    MyException,
)
from trigger_utils.trigger_utils import (
    submit_plan,
    get_plan_stats,
    trigger_ztf,
    update_trigger_log,
    send_trigger_email,
)
from utils.log import Logger
import yaml
import time
from astropy.time import Time

# settings for cadence bot
from utils.parser import followup_parser_args

args = followup_parser_args()
testing = args.testing
path_data = args.path_data


with open("config/Credentials.yaml", "r") as file:
    credentials = yaml.safe_load(file)
kowalskiusername = credentials["kowalski_username"]
kowalskipassword = credentials["kowalski_password"]

# set up logging that writes messages locally, sends to slack, and sends emails
if testing:
    webhook = credentials["slack_webhook_testing"]
else:
    webhook = credentials["slack_webhook"]

logger = Logger(webhook, filename="cadence")

logger.log(f"Starting cadence.py at at {Time.now()} with testing = {testing}")

# choose whether we use preview.fritz or fritz api
if testing:
    mode = "preview."
    fritz_token = credentials["preview_fritz_token"]
    allocation = credentials["preview_allocation"]
else:
    mode = ""
    fritz_token = credentials["fritz_token"]
    allocation = credentials["allocation"]

# look at any pending observations and determine whether we were successful in observing, if within 2 days automatically retry
retry = parse_pending_observation(
    path_data, fritz_token, kowalskiusername, kowalskipassword, mode
)
logger.log(f"retry: {retry}")

# check if it is time for any follow-up triggers
followup = trigger_on_cadence(path_data)
logger.log(f"followup: {followup}")

# handle follow-up triggers both for those in the scheduled cadence and for those that were unsuccessful
new_triggers = followup + retry

if new_triggers:
    for x in new_triggers:
        # request new plan and submit if good
        try:
            retrigger_type, superevent_id, gcnevent_id, localization_id, dateobs = (
                x[0],
                x[1],
                int(x[2]),
                int(x[3]),
                x[4],
            )
            # submit a plan request
            logger.log(f"Submitting plan request for {superevent_id}")
            queuename = submit_plan(
                fritz_token,
                allocation,
                superevent_id,
                gcnevent_id,
                localization_id,
                mode,
            )

            # retrieve observation plan for event from Fritz
            time.sleep(15)
            end_time = time.time() + 300
            fritz_event_status = None
            while fritz_event_status is None and time.time() < end_time:
                fritz_event_status = get_plan_stats(
                    gcnevent_id, queuename, fritz_token, mode
                )
                time.sleep(30)
            if fritz_event_status is None:
                logger.log(f"Could not find an observing plan for {superevent_id}")
                raise MyException(
                    f"Could not find an observing plan for {superevent_id}"
                )

            # check plan stats
            total_time = fritz_event_status[1]
            probability = fritz_event_status[2]
            start_observation = fritz_event_status[3]
            observation_plan_request_id = fritz_event_status[4]

            if total_time > 5400 or probability < 0.5:
                log_value = f"({observation_plan_request_id},{start_observation})"
                update_trigger_log(
                    superevent_id,
                    "unsuccessful_observation",
                    log_value,
                    path_data=path_data,
                    append_string=True,
                )
                message = f"Followup plan for {superevent_id} with {total_time} seconds and {probability} probability does not meet criteria"
                logger.log(message)
                raise MyException(message)

            logger.log(
                f"Plan for {superevent_id} has {total_time} seconds and {probability} probability - should trigger ZTF"
            )

            if testing:
                message = (
                    f"Testing mode, not actually triggering ZTF for {superevent_id}"
                )
                logger.log(message)
                raise MyException(message)

            # send plan to ZTF queue
            logger.log(f"Triggering ZTF for {superevent_id} in 30 seconds")
            time.sleep(30)
            trigger_ztf(observation_plan_request_id, fritz_token, mode)
            log_value = f"({observation_plan_request_id},{start_observation})"
            update_trigger_log(
                superevent_id,
                "pending_observation",
                log_value,
                path_data=path_data,
                append_string=True,
            )
            # email
            if retrigger_type == "followup":
                message = f"ZTF Triggered for a scheduled follow-up observation of {superevent_id}"
            else:
                message = f"Sending another trigger for tonight after unsuccessful observation of {superevent_id}"
            send_trigger_email(credentials, message, dateobs)
            logger.log(f"sent email: {message}")

        except MyException as e:
            logger.log(e)
            continue
