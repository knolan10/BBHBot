import pandas as pd
from astropy.time import Time, TimeDelta
import requests
import json
from .trigger_utils import update_trigger_log, SkymapCoverage


class MyException(Exception):
    pass


def check_pending_observations(df):
    """
    Check if we have pending observations
    """
    check_pending = []

    for row in df.itertuples(index=False):
        if row.valid != "True":
            continue
        pending = row.pending_observation
        if pd.isna(pending):
            continue
        supereventid = row.superevent_id
        items = pending.split("),(")
        items_list = [
            (int(item.split(",")[0].strip("()")), item.split(",")[1].strip("()"))
            for item in items
        ]
        print(f"Found {len(items_list)} pending observation for {supereventid}")
        current_date = Time.now()
        for item in items_list:
            observation_plan_id, start_observation = item[0], item[1]
            # if it is before the time for observation, don't do anything yet
            if current_date < Time(start_observation):
                print(
                    f"Observation of {supereventid} scheduled for {start_observation} - will check tomorrow"
                )
                continue
            # if the current date is within 2 days after start_observation, check if we observed
            time_difference = abs((current_date - Time(start_observation)).jd)
            if time_difference <= 2:
                gcnid = row.gcn_id
                localizationid = row.localization_id
                dateobs = row.dateobs
                print(
                    f"will check status of pending observation for {supereventid} on {start_observation}"
                )
                format_item = f"({item[0]},{item[1]})"
                check_pending.append(
                    [
                        True,
                        supereventid,
                        format_item,
                        gcnid,
                        localizationid,
                        observation_plan_id,
                        dateobs,
                        start_observation,
                    ]
                )
            else:
                # this will make event be moved to unsuccessful observation
                check_pending.append(
                    [False, supereventid, pending, None, None, None, None, None]
                )
    return check_pending


# TODO - just replace this with function get_plan_stats in utils/trigger_utils.py
def get_plan_prob(gcnevent_id, observation_plan_id, token, mode):
    """
    given the gcn event id and specific plan id, get the probability covered by the plan
    """
    try:
        headers = {"Authorization": f"token {token}"}
        endpoint = f"https://{mode}fritz.science/api/gcn_event/{gcnevent_id}/observation_plan_requests"
        response = requests.request("GET", endpoint, headers=headers)
        if response.status_code == 200:
            json_string = response.content.decode("utf-8")
            json_data = json.loads(json_string)

        if len(json_data["data"]) == 0:
            raise MyException(f"No requests found for {gcnevent_id}")
        generated_plan = [
            x
            for x in json_data["data"]
            if x["observation_plans"][0]["observation_plan_request_id"]
            == observation_plan_id
        ]
        if len(generated_plan) == 0:
            raise MyException(f"No generated plan for {gcnevent_id}")
        observation_plans = generated_plan[0]["observation_plans"]
        if len(observation_plans) == 0:
            raise MyException(f"No observation plans for {gcnevent_id}")
        elif len(observation_plans) > 1:
            raise MyException(f"Multiple observation plans for {gcnevent_id}")

        stats = observation_plans[0]["statistics"]
        # make sure there is one entry for observing plan here
        if len(stats) > 1:
            raise MyException(f"Multiple statistics found for {gcnevent_id}")
        elif len(stats) == 0:
            raise MyException(f"No statistics found for {gcnevent_id}")

        stats = observation_plans[0]["statistics"][0]
        probability = stats["statistics"]["probability"]
        return probability

    except MyException as e:
        print(f"error: {e}")
        return None


def parse_pending_observation(
    path_data, fritz_token, kowalski_username, kowalski_password, mode
):
    # open log of triggers
    trigger_log = pd.read_csv(
        f"{path_data}/trigger_data/triggered_events.csv",
        dtype={"gcn_id": "Int64", "localization_id": "Int64"},
    )
    retry = []
    pending = check_pending_observations(trigger_log)
    if pending:
        for x in pending:
            try:
                within_time = x[0]
                superevent_id = x[1]
                observation_info = x[2]
                gcnid = x[3]
                localizationid = x[4]
                observation_plan_id = x[5]
                dateobs = x[6]
                startdate = x[7]

                if not within_time:
                    # ~2 days post trigger and still unsuccessful - handle manually
                    update_trigger_log(
                        superevent_id,
                        "unsuccessful_observation",
                        observation_info,
                        path_data=path_data,
                        append_string=True,
                    )
                    update_trigger_log(
                        superevent_id,
                        "pending_observation",
                        observation_info,
                        path_data=path_data,
                        remove_string=True,
                    )
                    print(
                        f"We did not sucessfully observe the queued plans for {superevent_id}"
                    )
                    continue

                # check if executed observation was successful
                fraction_covered_in_plan = get_plan_prob(
                    localizationid, observation_plan_id, fritz_token, mode
                )
                skymap_name = "bayestar.multiorder.fits,2"  # TODO : find the most recent skymap, make sure this exists?
                enddate = (Time(startdate) + TimeDelta(3, format="jd")).iso
                observations = SkymapCoverage(
                    startdate,
                    enddate,
                    dateobs,
                    skymap_name,
                    localprob=0.9,
                    fritz_token=fritz_token,
                    kowalski_username=kowalski_username,
                    kowalski_password=kowalski_password,
                )
                frac_observed = observations.get_coverage_fraction()
                if (
                    frac_observed >= 0.8 * fraction_covered_in_plan
                ):  # TODO: fix coverage function and remove 0.8*
                    print(f"Observation of {superevent_id} successful")
                    update_trigger_log(
                        superevent_id,
                        "successful_observation",
                        observation_info,
                        path_data=path_data,
                        append_string=True,
                    )
                    update_trigger_log(
                        superevent_id,
                        "pending_observation",
                        observation_info,
                        path_data=path_data,
                        remove_string=True,
                    )
                elif frac_observed > 0:
                    print("Observation partially successful - visually inspect")
                    # TODO: build out this case handling
                else:
                    retry.append(
                        ["retry", superevent_id, gcnid, localizationid, dateobs]
                    )
                    print(
                        f"Trigger not successful for {superevent_id} - retrying for tonight"
                    )

            except MyException as e:
                print(e)
                continue
    return retry


def trigger_on_cadence(path_data):
    """
    Follow-up triggers based on trigger_cadence
    times in UTC time
    """

    df = pd.read_csv(
        f"{path_data}/trigger_data/triggered_events.csv",
        dtype={"gcn_id": "Int64", "localization_id": "Int64"},
    )
    df["gcn_id"] = df["gcn_id"].astype("int", errors="ignore")
    df["localization_id"] = df["localization_id"].astype("int", errors="ignore")

    trigger = []
    for row in df.itertuples(index=False):
        if row.valid != "True":
            continue
        cadence_str = row.trigger_cadence
        cadence = cadence_str.strip("[]").replace("'", "").split(", ")
        current_date = Time.now().strftime("%Y-%m-%d")
        for cadence_date in cadence:
            if Time(current_date) == Time(cadence_date):
                supereventid = row.superevent_id
                gcnid = row.gcn_id
                localizationid = row.localization_id
                dateobs = row.dateobs
                trigger.append(
                    ["followup", supereventid, gcnid, localizationid, dateobs]
                )
                print(f"Found follow-up trigger: {supereventid} on {cadence_date}")
    return trigger
