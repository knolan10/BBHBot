from gcn_kafka import Consumer
import yaml
import time
import pickle
import random
import threading
from astropy.time import Time, TimeDelta
from ligo.gracedb.exceptions import HTTPError

from trigger_utils.trigger_utils import (
    parse_gcn_dict,
    get_params,
    check_triggered_csv,
    SkymapCoverage,
    query_fritz_gcn_events,
    query_kowalski_ztf_queue,
    query_mchirp_gracedb,
    m_total_mlp,
    generate_cadence_dates,
    submit_plan,
    update_trigger_log,
    delete_trigger_ztf,
    get_plan_stats,
    check_before_sunset,
    trigger_ztf,
    add_triggercsv,
    send_trigger_email,
    MyException,
)
from utils.log import Logger

with open("config/Credentials.yaml", "r") as file:
    credentials = yaml.safe_load(file)
testing = credentials["testing"]
path_data = credentials["path_data"]
kowalskiusername = credentials["kowalski_username"]
kowalskipassword = credentials["kowalski_password"]

# set up logging that writes messages locally, sends to slack, and sends emails
if testing:
    webhook = credentials["slack_webhook_testing"]
else:
    webhook = credentials["slack_webhook"]

logger = Logger(webhook, filename="trigger")

logmessage = f"Starting TriggerBot with testing = {testing}"
logger.log(logmessage)

# choose whether we use preview.fritz or fritz api
if testing:
    mode = "preview."
    fritz_token = credentials["preview_fritz_token"]
    allocation = credentials["preview_allocation"]
else:
    mode = ""
    fritz_token = credentials["fritz_token"]
    allocation = credentials["allocation"]

# settings to subscribe to the Kafka topics
if testing:
    configid = f"BBHBOT_test{random.randint(0, 1000000)}"
    topics = ["gcn.classic.voevent.LVC_INITIAL", "gcn.classic.voevent.LVC_UPDATE"]
else:
    configid = credentials["config_id"]
    topics = [
        "gcn.classic.voevent.LVC_PRELIMINARY",
        "gcn.classic.voevent.LVC_INITIAL",
        "gcn.classic.voevent.LVC_UPDATE",
    ]

config = {
    "group.id": configid,
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
    "max.poll.interval.ms": 600050,
}

consumer = Consumer(
    config=config,
    client_id=credentials["client_id"],
    client_secret=credentials["client_secret"],
    domain="gcn.nasa.gov",
)

consumer.subscribe(topics)
logger.log(f"subscribed to Kafka consumer with groupid {configid} and topics {topics}")

# heartbeat will print a message every minute
heartbeat_thread = threading.Thread(target=logger.heartbeat())
heartbeat_thread.daemon = True
heartbeat_thread.start()

while True:
    try:
        for message in consumer.consume(timeout=1.0):
            if message.value() is None:
                print("No message received")
                continue
            try:
                value = message.value()
                parsed = parse_gcn_dict(value)
                params = get_params(parsed)
                dateobs = params[0]
                mjd = params[1]
                superevent_id = params[2]
                significant = params[3]
                alert_type = params[4]
                group = params[5]
                prob_bbh = params[6]
                prob_ter = params[7]
                far = params[8]
                distmean = params[9]
                a90 = params[10]
                skymap_name = params[11]

                # open triggered_events.csv and check for superevent_id
                triggered, trigger_plan_id = check_triggered_csv(
                    superevent_id, path_data
                )

                if (
                    superevent_id[0] != "S"
                    or alert_type == "RETRACTION"
                    or significant != "1"
                    or group != "CBC"
                    or prob_bbh < 0.5
                    or prob_ter > 0.4
                    or distmean == "error"
                    or far < 10
                    or a90 > 1000
                    or (alert_type == "Preliminary" and skymap_name[-1] == 0)
                ):
                    if triggered:
                        # try to remove trigger from ZTF queue
                        update_trigger_log(
                            superevent_id, "valid", False, path_data=path_data
                        )
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                        logger.log(f"attempting to remove trigger for {superevent_id}")
                    logmessage = f"{superevent_id} did not pass initial criteria"
                    logger.log(logmessage)
                    raise MyException(logmessage)

                logger.log(f"Processing {superevent_id} from {alert_type} alert")

                end_time = time.time() + 600
                mchirp = None
                while mchirp is None and time.time() < end_time:
                    try:
                        # grab the left bin edge for the most probable mchirp bin
                        mchirp = query_mchirp_gracedb(
                            superevent_id, path_data=path_data
                        )
                        # trigger on most probable bins >= 22
                        if mchirp and mchirp < 22:
                            if triggered:
                                update_trigger_log(
                                    superevent_id, "valid", False, path_data=path_data
                                )
                                delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                                logger.log(
                                    f"attempting to remove trigger for {superevent_id}"
                                )
                            logmessage = f"{superevent_id} did not pass mass criteria"
                            logger.log(logmessage)
                            raise MyException(logmessage)

                    except HTTPError:
                        logmessage = f"GraceDB HTTPError for {superevent_id}, retrying in 60 seconds"
                        logger.log(logmessage)

                    time.sleep(60)
                if mchirp is None:
                    # revert to the mass prediction
                    logmessage = f"Could not find a chirp mass file on GraceDB for {superevent_id}"
                    logger.log(logmessage)
                    MLP = pickle.load(open("utils/mlp_model.sav", "rb"))
                    mass = m_total_mlp(MLP, distmean, far, dl_bns=168.0)
                    if mass < 60:
                        if triggered:
                            update_trigger_log(
                                superevent_id, "valid", False, path_data=path_data
                            )
                            delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                            logger.log(
                                f"attempting to remove trigger for {superevent_id}"
                            )
                        logmessage = f"{superevent_id} did not pass mass criteria"
                        logger.log(logmessage)
                        raise MyException(logmessage)
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                        logger.log(f"attempting to remove trigger for {superevent_id}")
                    logmessage = f"{superevent_id} did not pass mass criteria"
                    logger.log(logmessage)
                    raise MyException(logmessage)

                logger.log(f"{superevent_id} passed mass criteria")

                # find gcn event on fritz
                if not testing:
                    time.sleep(30)
                    end_time = time.time() + 300
                else:
                    end_time = time.time() + 1
                gcnevent_id = None
                while gcnevent_id is None and time.time() < end_time:
                    gcnevent_id, localization_id = query_fritz_gcn_events(
                        dateobs, skymap_name, fritz_token, mode
                    )
                    time.sleep(30)
                if gcnevent_id is None:
                    logmessage = (
                        f"Could not find a GCN event on Fritz for {superevent_id}"
                    )
                    logger.log(logmessage)
                    raise MyException(logmessage)

                # submit plan request to Fritz
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
                    logmessage = f"Could not find an observing plan for {superevent_id}"
                    logger.log(logmessage)
                    raise MyException(logmessage)

                # API call to Kowalski - check for event keywords in ZTF observing queue
                if not testing:
                    keyword_list = [dateobs, superevent_id, gcnevent_id]
                    kowalski_event_status = query_kowalski_ztf_queue(
                        keyword_list, fritz_token, allocation
                    )
                    logger.log(
                        f"checked ZTF observing queue for key words related to {superevent_id}"
                    )
                else:
                    kowalski_event_status = False

                # have we triggered on the event
                if fritz_event_status[0] or kowalski_event_status:
                    previous_trigger = True
                else:
                    previous_trigger = False

                # if another group has triggered on the event, we will not trigger
                if previous_trigger and not triggered:
                    logmessage = f"Previous trigger for {superevent_id}"
                    logger.log(logmessage)
                    raise MyException(logmessage)

                # do the plan stats pass our criteria
                total_time = fritz_event_status[1]
                probability = fritz_event_status[2]
                start_observation = fritz_event_status[3]
                observation_plan_request_id = fritz_event_status[4]

                if total_time > 5400 or probability < 0.5:
                    if triggered:
                        update_trigger_log(
                            superevent_id, "valid", False, path_data=path_data
                        )
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                        logger.log(f"attempting to remove trigger for {superevent_id}")
                    logmessage = f"Followup plan for {superevent_id} with {total_time} seconds and {probability} probability does not meet criteria"
                    logger.log(logmessage)
                    raise MyException(logmessage)
                # don't trigger on events older than 1 day
                if TimeDelta(Time.now().mjd - mjd, format="jd").value > 1:
                    logmessage = f"{superevent_id} is more than 1 day old"
                    logger.log(logmessage)
                    raise MyException(logmessage)

                # if we have triggered on earlier GCN, can we update trigger with more recent inference
                if triggered:
                    if not check_before_sunset():
                        logmessage = (
                            f"Too late to update submitted trigger for {superevent_id}"
                        )
                        logger.log(logmessage)
                        raise MyException(logmessage)
                    else:
                        # remove current submitted plan so we can submit new one
                        # TODO: verify that trigger is successfully removed, else raise exception
                        delete_trigger_ztf(trigger_plan_id, fritz_token, mode)
                        logmessage = f"Removing previous trigger for {superevent_id} so we can resubmit updated plan"
                        logger.log(logmessage)

                # check if ZTF survey naturally covered the skymap previous ~3 nights
                # TODO: require g and r separately
                enddate = Time(dateobs).jd
                startdate = enddate - TimeDelta(3, format="jd").value
                frac_observed = SkymapCoverage(
                    startdate,
                    enddate,
                    dateobs,
                    skymap_name,
                    localprob=0.9,
                    fritz_token=fritz_token,
                    fritz_mode=mode,
                    kowalski_username=kowalskiusername,
                    kowalski_password=kowalskipassword,
                ).get_coverage_fraction()
                if (
                    frac_observed >= 0.9 * probability
                ):  # TODO: what percentage do we want here? Either way, make sure it is documented
                    logmessage = f"There is recent coverage of {round(frac_observed * 100)} % of {superevent_id} - not triggering"
                    logger.log(logmessage)
                    serendipitious_observation = (
                        observation_plan_request_id,
                        start_observation,
                    )
                    message = f"Skipped ZTF triggered for {superevent_id} due to serendipitous coverage"
                else:
                    if testing:
                        logmessage = f"Plan for {superevent_id} is good - but dont trigger in testing mode"
                        logger.log(logmessage)
                    else:
                        # send plan to ZTF queue
                        time.sleep(30)
                        trigger_ztf(observation_plan_request_id, fritz_token, mode)
                        logger.log(f"Triggered ZTF for {superevent_id} at {Time.now()}")
                    message = f"ZTF Triggered for {superevent_id}"
                    serendipitious_observation = None

                # write to triggered_events.csv
                trigger_cadence = generate_cadence_dates(dateobs)
                gcn_type = (alert_type, skymap_name)
                queued_plan = (observation_plan_request_id, start_observation)
                valid = True
                if serendipitious_observation:
                    queued_plan = None
                add_triggercsv(
                    superevent_id,
                    dateobs,
                    gcn_type,
                    gcnevent_id,
                    localization_id,
                    trigger_cadence,
                    queued_plan,
                    serendipitious_observation,
                    valid,
                    path_data,
                )
                send_trigger_email(credentials, message, dateobs)

                logger.log("post-trigger sleep")
                time.sleep(
                    120
                )  # after triggering pause to avoid double triggers on quickly updated gcn

            except MyException as e:
                logger.log(e)
                continue

            finally:
                consumer.commit(message)

    except Exception as e:
        logger.log(e)
        continue
