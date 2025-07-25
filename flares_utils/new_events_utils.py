import pandas as pd
from pandas import json_normalize
import numpy as np
import matplotlib.pyplot as plt
from astropy.table import Table
import astropy.cosmology as cos
from astropy.cosmology import Planck15 as cosmo
import astropy_healpix as ah
import astropy.units as u
from astropy.time import Time
from datetime import datetime, timedelta
import requests
from io import BytesIO
import xmltodict
import pickle
import gzip
import base64
import json
import os
from ligo.skymap.io import read_sky_map
import ligo.skymap.plot
import ligo.skymap.postprocess
from ligo.gracedb.rest import GraceDb
from penquins import Kowalski
from matplotlib import rcParams

from trigger_utils.trigger_utils import (
    query_mchirp_gracedb,
    m_total_mlp,
    get_a,
    SkymapCoverage,
)
from utils.log import Logger, PublishToGithub

# set up logger (this one wont send to slack)
logger = Logger(filename="cadence_utils")

rcParams["font.family"] = "Liberation Serif"


class MyException(Exception):
    pass


class GetSuperevents:
    def __init__(
        self,
        path_data,
        event_source,
        observing_run,
        kafka_response=None,
        retrieve_all=False,
    ):
        self.path_data = path_data
        self.event_source = event_source
        self.observing_run = observing_run
        self.kafka_response = kafka_response
        self.retrieve_all = retrieve_all
        self.g = GraceDb()

    # TODO : add a date to the gracedb query so we aren't getting all of 04b/O4c etc
    # TODO : add option to update all events, ie to catch updated alert values
    # TODO : return params as dictionary, remove these values: group, significant, prob_bbh, prob_ter, skymap_url, diststd, skymap_str, zmin, zmax, skymap

    """
    get new events that haven't been processed yet
    use get_new_events to return :
    superevent_id, event_page, alert_type, instrument, pipeline, group, significant, prob_bbh, prob_ter,
    far_format, skymap_url, date, fritz_dateid, distmean, diststd, dateobs_str, a90, a50, skymap_str, zmin,
    zmax, skymap, mass
    """

    def read_from_gracedb(self, ids, files):
        # TODO: assuming there is a better way to select the most recent gcn
        superevent_files = [i["links"]["files"] for i in files]
        event_files = [self.g.files(graceid).json() for graceid in ids]
        file = [
            "none"
            if any("etraction" in s for s in list(files))
            else id + "-5-Update.xml,0"
            if id + "-5-Update.xml,0" in list(files)
            else id + "-5-Update.xml"
            if id + "-5-Update.xml" in list(files)
            else id + "-4-Update.xml,0"
            if id + "-4-Update.xml,0" in list(files)
            else id + "-4-Update.xml"
            if id + "-4-Update.xml" in list(files)
            else id + "-3-Update.xml,0"
            if id + "-3-Update.xml,0" in list(files)
            else id + "-2-Update.xml,0"
            if id + "-2-Update.xml,0" in list(files)
            else id + "-4-Initial.xml,0"
            if id + "-4-Initial.xml,0" in list(files)
            else id + "-3-Initial.xml,0"
            if id + "-3-Initial.xml,0" in list(files)
            else id + "-2-Initial.xml,0"
            if id + "-2-Initial.xml,0" in list(files)
            else id + "-2-Preliminary.xml,0"
            if id + "-2-Preliminary.xml,0" in list(files)
            else "none"
            for files, id in zip(event_files, ids)
        ]
        urls = [i + j for i, j in zip(superevent_files, file)]
        urls_save = [x for x in urls if "none" not in x]
        response = [requests.get(url).text for url in urls_save]
        return response

    def get_params(self, response):
        try:
            dict = xmltodict.parse(response)
            superevent_id = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "GraceID"
            ][0]
            event_page = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "EventPage"
            ][0]
            alert_type = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "AlertType"
            ][0]
            instrument = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "Instruments"
            ][0]
            pipeline = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "Pipeline"
            ][0]
            group = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "Group"
            ][0]
            significant = [
                item["@value"]
                for item in dict["voe:VOEvent"]["What"]["Param"]
                if item.get("@name") == "Significant"
            ][0]
            classification = [
                item
                for item in dict["voe:VOEvent"]["What"]["Group"]
                if item.get("@name") == "Classification"
            ]
            prob_bbh = float(
                [
                    item["@value"]
                    for item in classification[0]["Param"]
                    if item.get("@name") == "BBH"
                ][0]
            )
            prob_ter = float(
                [
                    item["@value"]
                    for item in classification[0]["Param"]
                    if item.get("@name") == "Terrestrial"
                ][0]
            )
            far = float(dict["voe:VOEvent"]["What"]["Param"][9]["@value"])
            far_format = 1.0 / (far * 3.15576e7)
            skymap_url = [
                item["Param"]["@value"]
                for item in dict["voe:VOEvent"]["What"]["Group"]
                if item.get("@name") == "GW_SKYMAP"
            ][0]
            date = dict["voe:VOEvent"]["Who"]["Date"]
            t0 = dict["voe:VOEvent"]["WhereWhen"]["ObsDataLocation"][
                "ObservationLocation"
            ]["AstroCoords"]["Time"]["TimeInstant"]["ISOTime"]
            dateobs = Time(t0, precision=0)
            dateobs = Time(dateobs.iso).datetime
            fritz_dateid = dateobs.strftime("%Y-%m-%dT%H:%M:%S")
            return (
                superevent_id,
                event_page,
                alert_type,
                instrument,
                pipeline,
                group,
                significant,
                prob_bbh,
                prob_ter,
                far_format,
                skymap_url,
                date,
                fritz_dateid,
            )
        except MyException as e:
            logmessage = f"error loading xml: {response}: {e}"
            logger.log(logmessage, slack=False)

    def proc_skymap(self, skymap_url):
        skymap_response = requests.get(skymap_url)
        skymap_bytes = skymap_response.content
        skymap = Table.read(BytesIO(skymap_bytes))
        skymap_str = base64.b64encode(skymap_bytes).decode("utf-8")
        return skymap, skymap_str

    def extract_skymap_params(self, skymap_url):
        skymap, skymap_str = self.proc_skymap(skymap_url)
        try:
            distmean = skymap.meta["DISTMEAN"]
            diststd = skymap.meta["DISTSTD"]
            t0 = skymap.meta["DATE-OBS"]
            dateobs = Time(t0, precision=0)
            dateobs = Time(dateobs.iso).datetime
            dateobs_str = dateobs.strftime("%Y-%m-%dT%H:%M:%S")
            a90 = get_a(skymap, 0.9)
            a50 = get_a(skymap, 0.5)
            if distmean - 3 * diststd > 0:
                zmin = cos.z_at_value(
                    cosmo.luminosity_distance,
                    (distmean - 3 * diststd) * u.Mpc,
                    method="bounded",
                ).value
            else:
                zmin = 0
            zmax = cos.z_at_value(
                cosmo.luminosity_distance,
                (distmean + 3 * diststd) * u.Mpc,
                method="bounded",
            ).value
            return (
                distmean,
                diststd,
                dateobs_str,
                a90,
                a50,
                skymap_str,
                zmin,
                zmax,
                skymap,
            )
        except MyException as e:
            logmessage = f"error loading skymap {skymap_url}: {e}"
            logger.log(logmessage, slack=False)
            return "None"

    def get_new_events(self):
        if self.event_source == "gracedb":
            event_iterator = self.g.superevents(
                f"runid: {self.observing_run} SIGNIF_LOCKED"
            )
            graceids = [superevent["superevent_id"] for superevent in event_iterator]
            logmessage = (
                f"{len(graceids)} significant superevents in {self.observing_run}"
            )
            logger.log(logmessage, slack=False)
            responses = [self.g.superevent(id) for id in graceids]
            data = [r.json() for r in responses]
            if not self.retrieve_all:
                with open(
                    f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
                    "r",
                ) as file:
                    events_dict_add = json.load(file)
                new_events = [
                    (i, j)
                    for i, j in zip(graceids, data)
                    if i not in list(events_dict_add.keys())
                ]
                graceids = [x[0] for x in new_events]
                data = [x[1] for x in new_events]
            response = self.read_from_gracedb(graceids, data)
        elif self.event_source == "kafka":
            response = [self.kafka_response]
        gcn_params = [self.get_params(url) for url in response]
        low_prob_bbh = [x for x in gcn_params if x[7] < 0.5 or x[8] > 0.3]
        params = [x for x in gcn_params if x[7] > 0.5 and x[8] < 0.3]
        logmessage = f"{len(params)} new events to process (cut {len(low_prob_bbh)} low prob bbh events)"
        logger.log(logmessage, slack=False)
        skymap_urls = [x[10] for x in params]
        skymap_data = [self.extract_skymap_params(url) for url in skymap_urls]
        # mass
        dist = [x[0] for x in skymap_data]
        far = [x[9] for x in params]
        mass = [
            m_total_mlp(self.path_data, d, f, dl_bns=168.0) for d, f in zip(dist, far)
        ]
        chirpmass = [query_mchirp_gracedb(str(x[0]), self.path_data) for x in params]
        return [
            list(i) + list(j) + [k] + [chirp]
            for i, j, k, chirp in zip(params, skymap_data, mass, chirpmass)
        ]


class Fritz:
    def __init__(
        self,
        eventid,
        dateid,
        a90,
        far,
        mass,
        allocation,
        fritz_token,
        kowalsi_username,
        kowalski_password,
    ):
        self.eventid = eventid
        self.dateid = dateid
        self.a90 = a90
        self.far = far
        self.mass = mass
        self.allocation = allocation
        self.fritz_token = fritz_token
        self.kowalski_username = kowalsi_username
        self.kowalski_password = kowalski_password

    def query_fritz_observation_plans(self, allocation, token):
        headers = {"Authorization": f"token {token}"}
        endpoint = f"https://fritz.science/api/allocation/observation_plans/{allocation}?numPerPage=1000"
        response = requests.request("GET", endpoint, headers=headers)
        if response.status_code == 200:
            json_string = response.content.decode("utf-8")
            json_data = json.loads(json_string)
            return json_data
        else:
            logmessage = (
                f"Error querying Fritz observation plans: {response.status_code}"
            )
            logger.log(logmessage, slack=False)
            return None

    # get the statistics for a potential observation plan
    def determine_trigger_status(
        self, observation_plans, eventid, dateid, a90, far, mass
    ):
        matching_requests = [
            x for x in observation_plans if x["localization"]["dateobs"] == dateid
        ]
        # handling events without plan requests
        if len(matching_requests) == 0:
            if datetime.fromisoformat(dateid) < datetime.fromisoformat(
                "2024-09-14T00:00:00"
            ):
                logmessage = f"{eventid} predates trigger"
                logger.log(logmessage, slack=False)
                return ["correct", "predates trigger"]
            else:
                if far < 10 or a90 > 1000 or mass < 60:
                    logmessage = f"Event doesnt pass criteria - correct no plan request for {eventid}"
                    logger.log(logmessage, slack=False)
                    return ["correct", "not triggered"]
                else:
                    logmessage = f"Error: should have requested plan for {eventid}"
                    logger.log(logmessage, slack=False)
                    trigger_status = "missed plan request"
                    return ["error", "missed plan request"]
        # now only considering events that have a plan request
        else:
            # check whether we triggered
            status = [x["status"] for x in matching_requests]
            if "submitted to telescope queue" in status:
                trigger_status = "triggered"
            else:
                trigger_status = "not triggered"

            # stop considering events that predate the trigger
            if datetime.fromisoformat(dateid) < datetime.fromisoformat(
                "2024-09-14T00:00:00"
            ):
                if trigger_status == "triggered":
                    logmessage = f"{eventid} trigger predating automated trigger"
                    logger.log(logmessage, slack=False)
                    return ["correct", "non-automated trigger"]
                else:
                    logmessage = f"{eventid} predates trigger"
                    logger.log(logmessage, slack=False)
                    return ["correct", "predates trigger"]
            # now down to events with plans while the trigger is operational
            else:
                # check whether we should have triggered on the event - need to get plan statistics to check this
                # the triggered case
                if trigger_status == "triggered":
                    # look at stats for the submitted plan
                    plans = [
                        x
                        for x in matching_requests
                        if x["status"] == "submitted to telescope queue"
                    ]
                    if len(plans) != 1:
                        logmessage = f"Multiple triggers: inspect {eventid}"
                        logger.log(logmessage, slack=False)
                        return ["inspect", "multiple triggers"]
                # the not triggered case
                else:
                    plans = [
                        x
                        for x in matching_requests
                        if x["observation_plans"][0]["statistics"]
                        and x["observation_plans"][0]["statistics"][0]["statistics"][
                            "num_observations"
                        ]
                        != 0
                    ]
                    if not plans:
                        if far < 10 or a90 > 1000 or mass < 60:
                            logmessage = f"requested plan when we shouldnt have but correctly didnt trigger - parameters dont pass criteria {eventid}"
                            logger.log(logmessage, slack=False)
                            return ["correct", "not triggered"]
                        else:
                            logmessage = f"No valid plans found for {eventid}"
                            logger.log(logmessage, slack=False)
                            return ["error", "no valid plan"]
                # for non triggered events take the most recent plan as truth, ie if earlier plan passes criteria but later one doesn't go by the later one
                most_recent_plan = max(plans, key=lambda x: x["modified"])
                observation_plan = most_recent_plan["observation_plans"]
                stats = observation_plan[0]["statistics"]
                total_time = stats[0]["statistics"]["total_time"]
                probability = stats[0]["statistics"]["probability"]
                start = stats[0]["statistics"]["start_observation"]
                # check serendiptious coverage case
                skymap_name = most_recent_plan["localization"]["localization_name"]
                frac_observed = SkymapCoverage(
                    localdateobs=dateid,
                    localname=skymap_name,
                    localprob=0.9,
                    fritz_token=self.fritz_token,
                    fritz_mode="",  # TODO: add testing fritz api mode?
                    kowalski_username=self.kowalski_username,
                    kowalski_password=self.kowalski_password,
                ).get_coverage_fraction()
                if frac_observed > 0.9 * probability:
                    serendipitious_observation = True
                else:
                    serendipitious_observation = False
                # independently get the intended trigger status
                if (
                    far < 10
                    or a90 > 1000
                    or mass < 60
                    or probability < 0.5
                    or total_time > 5400
                ):
                    intended_trigger_status = "not triggered"
                else:
                    intended_trigger_status = "triggered"
                # compare the trigger status to the intended trigger status
                if (
                    trigger_status == "triggered"
                    and intended_trigger_status == "triggered"
                ):
                    logmessage = f"triggered on {eventid}"
                    logger.log(logmessage, slack=False)
                    return ["correct", "triggered", total_time, probability, start]
                elif (
                    trigger_status == "triggered"
                    and intended_trigger_status == "not triggered"
                ):
                    logmessage = f"Error: bad trigger for {eventid}"
                    logger.log(logmessage, slack=False)
                    return ["error", "bad trigger", total_time, probability, start]
                elif (
                    trigger_status == "not triggered"
                    and intended_trigger_status == "triggered"
                ):
                    if serendipitious_observation:
                        logmessage = (
                            f"Correct no trigger: serendipitous coverage for {eventid}"
                        )
                        logger.log(logmessage, slack=False)
                        # note here we use dateid in place of plan start time bc we still want to generate future trigger cadence
                        start_proxy = (
                            dateid + ".000"
                        )  # TODO: make cadence func smarter at handling different input formats
                        return ["correct", "triggered", 0, frac_observed, start_proxy]
                    logmessage = f"Error: missed trigger for {eventid}"
                    logger.log(logmessage, slack=False)
                    return ["error", "missed trigger", total_time, probability, start]
                elif (
                    trigger_status == "not triggered"
                    and intended_trigger_status == "not triggered"
                ):
                    logmessage = f"not triggered on {eventid}"
                    logger.log(logmessage, slack=False)
                    return ["correct", "not triggered", total_time, probability, start]

    def get_trigger_status(self):
        plans = self.query_fritz_observation_plans(self.allocation, self.fritz_token)
        if not plans:
            raise ValueError("No plans found")
        observation_plan_requests = plans["data"]["observation_plan_requests"]
        trigger_status = [
            self.determine_trigger_status(observation_plan_requests, i, j, a, f, m)
            for i, j, a, f, m in zip(
                self.eventid, self.dateid, self.a90, self.far, self.mass
            )
        ]
        error = [(i, x) for i, x in enumerate(trigger_status) if x[0] == "error"]
        correct = [(i, x) for i, x in enumerate(trigger_status) if x[0] == "correct"]
        inspect = [(i, x) for i, x in enumerate(trigger_status) if x[0] == "inspect"]
        logmessage = (
            f"{len(error)} errors, {len(correct)} correct, {len(inspect)} inspect"
        )
        logger.log(logmessage, slack=False)
        for x in error:
            index = x[0]
            event = self.eventid[index]
            logmessage = f"error: {event}: {x[1][1]}"
            logger.log(logmessage, slack=False)
        maunual_edits = {
            "S240921cw": ["correct", "not triggered", 0, 0, ""],  # moon too close ?
            "S241125n": [
                "correct",
                "triggered",
                900,
                0.5,
                "",
            ],  # the Swift/Bat coincident detection
            "S241130n": ["correct", "not triggered", 0, 0, ""],  # sun too close ?
        }
        for key, value in maunual_edits.items():
            if key in self.eventid:
                i = self.eventid.index(key)
                trigger_status[i] = value
        return trigger_status


class NewEventsToDict:
    def __init__(self, params, trigger_status, path_data, observing_run, testing):
        self.params = params
        self.trigger_status = trigger_status
        self.path_data = path_data
        self.observing_run = observing_run
        self.testing = testing

    def generate_cadence_dates(self, input_dates):
        cadence = [7, 14, 21, 28, 40, 50]
        result = []
        for input_date_str in input_dates:
            if input_date_str == "":
                result.append("")
            else:
                input_date = datetime.strptime(input_date_str, "%Y-%m-%dT%H:%M:%S.%f")
                date_only = datetime(input_date.year, input_date.month, input_date.day)
                new_dates = [
                    (date_only + timedelta(days=days)).strftime("%Y-%m-%d")
                    for days in cadence
                ]
                result.append(new_dates)
        return result

    def save_data(self):
        ids = [x[0] for x in self.params]
        far_format = [
            "{:.1e}".format(x[13]) if x[9] > 1000 else "{:.1f}".format(x[9])
            for x in self.params
        ]
        mass_format = [round(x[22]) for x in self.params]
        chirp_mass_format = [int(x[23]) for x in self.params]
        dist_format = [round(x[13] / 10**3, 2) for x in self.params]
        a50_format = [round(x[17]) for x in self.params]
        a90_format = [round(x[16]) for x in self.params]
        mjd = [round(Time(x[15], format="fits").mjd) for x in self.params]
        gcnid = [
            Time(x[15], format="isot", scale="utc").iso.split(".")[0].replace(" ", "T")
            for x in self.params
        ]
        trigger = [x[1] for x in self.trigger_status]
        total_time = [int(x[2]) if len(x) > 2 else "" for x in self.trigger_status]
        probability = [
            int(round(x[3], 2)) if len(x) > 2 else "" for x in self.trigger_status
        ]
        start = [x[4] if len(x) > 2 else "" for x in self.trigger_status]
        obs_cadence = self.generate_cadence_dates(start)
        new_events_df = pd.DataFrame(
            {
                "graceids": ids,
                "GW MJD": mjd,
                "90% Area (deg2)": a90_format,
                "50% Area (deg2)": a50_format,
                "Distance (Gpc)": dist_format,
                "FAR (years/FA)": far_format,
                "Mass (M_sol)": mass_format,
                "Chirp Mass (left edge)": chirp_mass_format,
                "gcnids": gcnid,
                "trigger": trigger,
                "plan time": total_time,
                "plan probability": probability,
                "plan start": start,
                "cadence": obs_cadence,
            }
        )

        new_events_df["FAR (years/FA)"] = pd.to_numeric(
            new_events_df["FAR (years/FA)"], downcast="integer"
        )

        new_events_df.set_index("graceids", inplace=True)
        df_for_dict = new_events_df.drop(
            columns=["plan time", "plan probability", "plan start", "cadence"]
        )
        new_events_dict = df_for_dict.to_dict(orient="index")

        with open(
            f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
            "r",
        ) as file:
            events_dict_add = json.load(file)

        # add any new events to saved dict
        for key in new_events_dict.keys():
            if key not in events_dict_add.keys():
                events_dict_add[key] = {}
                events_dict_add[key]["gw"] = new_events_dict[key]
                events_dict_add[key]["crossmatch"] = {}
                events_dict_add[key]["flare"] = {}

            keys_to_update = [
                "Days since GW",
                "90% Area (deg2)",
                "50% Area (deg2)",
                "Distance (Gpc)",
                "FAR (years/FA)",
                "Mass (M_sol)",
                "Chirp Mass (left edge)",
                "gcnids",
                "trigger",
            ]
            for subkey in new_events_dict[key].keys():
                if subkey in keys_to_update:
                    events_dict_add[key]["gw"][subkey] = new_events_dict[key][subkey]

            # Add subkeys for total times and probability for triggered events and good events that werent triggered (likely failed on plan)
            if new_events_dict[key]["trigger"] in [
                "triggered",
                "bad trigger",
            ] or key in ["S241210cw", "S241130n", "S241129aa", "S240924a"]:
                events_dict_add[key]["gw"]["trigger plan"] = {}
                events_dict_add[key]["gw"]["trigger plan"]["time"] = (
                    int(new_events_df.at[key, "plan time"])
                    if "plan time" in new_events_df.columns
                    else None
                )
                events_dict_add[key]["gw"]["trigger plan"]["probability"] = (
                    int(new_events_df.at[key, "plan probability"])
                    if "plan probability" in new_events_df.columns
                    else None
                )
                events_dict_add[key]["gw"]["trigger plan"]["start"] = (
                    new_events_df.at[key, "plan start"]
                    if "plan start" in new_events_df.columns
                    else None
                )
                events_dict_add[key]["gw"]["trigger plan"]["cadence"] = (
                    new_events_df.at[key, "cadence"]
                    if "cadence" in new_events_df.columns
                    else None
                )

        if len(new_events_df) == 0:
            logmessage = "No new events to add"
            logger.log(logmessage, slack=False)
            return None

        if not self.testing:  # save automatically
            with open(
                f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
                "w",
            ) as file:
                json.dump(events_dict_add, file)
            logmessage = "New events saved to dictionary."
            logger.log(logmessage, slack=False)
        return new_events_df


class KowalskiCrossmatch:
    def __init__(
        self,
        localization_name,
        skymap_str,
        dateobs,
        zmin,
        zmax,
        path_data,
        observing_run,
        catalogs=["catnorth"],
        mindec=-90,
        contour=90,
        testing=False,
        kowalski_username=None,
        kowalski_password=None,
    ):
        self.localization_name = localization_name
        self.skymap_str = skymap_str
        self.dateobs = dateobs
        self.zmin = zmin
        self.zmax = zmax
        self.path_data = path_data
        self.observing_run = observing_run
        self.catalogs = catalogs
        self.mindec = mindec
        self.contour = contour
        self.testing = testing
        self.kowalski_username = kowalski_username
        self.kowalski_password = kowalski_password
        self.kowalski = self.connect_kowalski()

    def connect_kowalski(self):
        instances = {
            "kowalski": {
                "name": "kowalski",
                "host": "kowalski.caltech.edu",
                "protocol": "https",
                "port": 443,
                "username": self.kowalski_username,
                "password": self.kowalski_password,
                "timeout": 6000,
            },
            "gloria": {
                "name": "gloria",
                "host": "gloria.caltech.edu",
                "protocol": "https",
                "port": 443,
                "username": self.kowalski_username,
                "password": self.kowalski_password,
                "timeout": 6000,
            },
        }
        kowalski = Kowalski(instances=instances)
        return kowalski

    def check_events_crossmatch(self):
        # events with crossmatch
        crossmatch_path = (
            f"{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz"
        )
        if os.path.exists(crossmatch_path):
            with gzip.open(crossmatch_path, "rb") as f:
                crossmatch_dict = pickle.load(f)
        ids_with_crossmatch = set(crossmatch_dict.keys())
        # events missing crossmatch
        with open(
            f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
            "r",
        ) as file:
            events_dict_add = json.load(file)
        ids_missing_crossmatch = [
            key for key, value in events_dict_add.items() if not value["crossmatch"]
        ]
        return ids_with_crossmatch, ids_missing_crossmatch

    def load_skymap_to_kowalski(
        self, kowalski, localization_name, skymapstring, date, contour, machine
    ):
        skymap_data = {
            "localization_name": localization_name,
            "content": skymapstring,
        }
        kowalski.api(
            "put",
            "api/skymap",
            data={"dateobs": date, "skymap": skymap_data, "contours": contour},
            name=machine,
        )

    def crossmatch_catnorth(
        self, kowalski, localization_name, contour, date, zmin, zmax, mindec
    ):
        """
        crossmatch catnorth with the ligo skymap
        """
        query = {
            "query_type": "skymap",
            "query": {
                "skymap": {
                    "localization_name": localization_name,
                    "contour": contour,
                    "dateobs": date,
                },
                "catalog": "CatNorth",
                "filter": {
                    "z_ph": {"$gte": zmin, "$lte": zmax},
                    "dec": {"$gte": mindec},
                },
                "projection": {"ra": 1, "dec": 1, "z_xp_nn": 1},
            },
        }
        response_catnorth_localization = kowalski.query(query=query)
        selected_agn = response_catnorth_localization.get("gloria", {}).get("data", [])
        logmessage = f"{len(selected_agn)} CATNorth AGN found in localization volume for {localization_name}"
        logger.log(logmessage, slack=False)
        return selected_agn

    def crossmatch_quaia(
        self, kowalski, localization_name, contour, date, zmin, zmax, mindec
    ):
        """
        crossmatch quaia_G20.5 with the ligo skymap
        """
        query = {
            "query_type": "skymap",
            "query": {
                "skymap": {
                    "localization_name": localization_name,
                    "contour": contour,
                    "dateobs": date,
                },
                "catalog": "quaia_G20.5",
                "filter": {
                    "redshift_quaia": {"$gte": zmin, "$lte": zmax},
                    "dec": {"$gte": mindec},
                },
                "projection": {
                    "ra": 1,
                    "dec": 1,
                    "redshift_quaia": 1,
                    "unwise_objid": 1,
                },
            },
        }
        response_quaia_localization = kowalski.query(query=query, name="kowalski")
        selected_agn = response_quaia_localization.get("kowalski", {}).get("data", [])
        converted_selected_agn = [
            {**entry, "_id": str(entry["_id"])} for entry in selected_agn
        ]
        logmessage = f"{len(converted_selected_agn)} Quaia AGN found in localization volume for {localization_name}"
        logger.log(logmessage, slack=False)
        return converted_selected_agn

    def delete_skymaps(self, kowalski, dateobs, localization_name, machine):
        """
        delete skymaps for cleanup
        """
        kowalski.api(
            "delete",
            "api/skymap",
            data={"dateobs": dateobs, "localization_name": localization_name},
            name=machine,
        )

    def sort_coords_by_prob(self, skymapstring, coords):
        """
        order coords based on skymap probability, so when we submit to ZFPS we submit highest prob first
        """
        # test this
        skymap = Table.read(BytesIO(base64.b64decode(skymapstring)))
        max_level = 29  # arbitrarily high resolution
        max_nside = ah.level_to_nside(max_level)
        level, ipix = ah.uniq_to_level_ipix(skymap["UNIQ"])
        index = ipix * (2 ** (max_level - level)) ** 2
        sorter = np.argsort(index)
        agn_prob = []
        for coord in coords:
            ra, dec = coord["ra"] * u.deg, coord["dec"] * u.deg
            match_ipix = ah.lonlat_to_healpix(ra, dec, max_nside, order="nested")
            i = sorter[
                np.searchsorted(index, match_ipix, side="right", sorter=sorter) - 1
            ]
            prob = skymap[i]["PROBDENSITY"]  # .to_value(u.deg**-2)
            agn_prob.append(prob)
        paired = list(zip(agn_prob, coords))
        paired_sorted = sorted(paired, key=lambda x: x[0], reverse=True)
        if not paired_sorted:
            return []
        prob_sorted, coords_sorted = zip(*paired_sorted)
        return list(coords_sorted)

    def get_crossmatches(self, crossmatch_new_only=True):
        """
        get catnorth and quaia crossmatches
        """
        kowalski = self.kowalski
        localization_name = self.localization_name
        skymap_str = self.skymap_str
        contour = self.contour
        date = self.dateobs
        zmin = self.zmin
        zmax = self.zmax
        mindec = self.mindec

        # sort which events to crossmatch
        ids_with_crossmatch, ids_missing_crossmatch = self.check_events_crossmatch()

        for id in ids_missing_crossmatch:
            if id not in localization_name:
                logmessage = f"Warning: {id} is missing crossmatch data but not provided in input list"
                logger.log(logmessage, slack=False)

        if crossmatch_new_only:
            ids_to_crossmatch = []
            for id in localization_name:
                if id not in ids_with_crossmatch:
                    ids_to_crossmatch.append(id)
                else:
                    logmessage = f"Skipping {id} bc already crossmatched"
                    logger.log(logmessage, slack=False)
        else:
            ids_to_crossmatch = localization_name

        logmessage = (
            f"Crossmatching {len(ids_to_crossmatch)} events: {ids_to_crossmatch}"
        )
        logger.log(logmessage, slack=False)

        # do crossmatch
        if "catnorth" in self.catalogs:
            [
                self.load_skymap_to_kowalski(
                    kowalski, local, skymap, dat, contour, "gloria"
                )
                for local, skymap, dat in zip(localization_name, skymap_str, date)
                if local in ids_to_crossmatch
            ]
            catnorth_unsorted = [
                self.crossmatch_catnorth(kowalski, local, contour, dat, zn, zx, mindec)
                for local, dat, zn, zx in zip(localization_name, date, zmin, zmax)
                if local in ids_to_crossmatch
            ]
            # sort catnorth so highest prob first
            catnorth = [
                self.sort_coords_by_prob(i, j)
                for i, j in zip(skymap_str, catnorth_unsorted)
            ]
            [
                self.delete_skymaps(kowalski, dat, local, "gloria")
                for dat, local in zip(date, localization_name)
                if local in ids_to_crossmatch
            ]
        else:
            catnorth = [None] * len(ids_to_crossmatch)

        if "quaia" in self.catalogs:
            [
                self.load_skymap_to_kowalski(
                    kowalski, local, skymap, dat, contour, "kowalski"
                )
                for local, skymap, dat in zip(localization_name, skymap_str, date)
                if local in ids_to_crossmatch
            ]
            quaia = [
                self.crossmatch_quaia(kowalski, local, contour, dat, zn, zx, mindec)
                for local, dat, zn, zx in zip(localization_name, date, zmin, zmax)
                if local in ids_to_crossmatch
            ]
            [
                self.delete_skymaps(kowalski, dat, local, "kowalski")
                for dat, local in zip(date, localization_name)
                if local in ids_to_crossmatch
            ]
        else:
            quaia = [None] * len(ids_to_crossmatch)

        # save coords for catnorth crossmatch
        if not catnorth:
            logmessage = "No catnorth crossmatch"
            logger.log(logmessage, slack=False)
        else:
            # open saved crossmatch dict
            crossmatch_path = f"{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz"
            if os.path.exists(crossmatch_path):
                with gzip.open(crossmatch_path, "rb") as f:
                    crossmatch_dict_add = pickle.load(f)
            else:
                crossmatch_dict_add = {}
            # new entries
            crossmatch_dict = {
                name: {"agn_catnorth": coords}
                for name, coords in zip(ids_to_crossmatch, catnorth)
            }
            for key, value in crossmatch_dict.items():
                if key not in crossmatch_dict_add:
                    logmessage = f"{key} added to crossmatch dict"
                    logger.log(logmessage, slack=False)
                else:
                    logmessage = f"{key} replaced previously saved crossmatch"
                    logger.log(logmessage, slack=False)
                crossmatch_dict_add[key] = value
            if not self.testing:
                with gzip.open(crossmatch_path, "wb") as f:
                    f.write(pickle.dumps(crossmatch_dict_add))

            # save stats on crossmatch
            catnorth_count = [len(c) if c else None for c in catnorth]
            quaia_count = [len(q) if q else None for q in quaia]
            crossmatch_dict_stats = {
                id: {"n_agn_catnorth": c, "n_agn_quaia": q}
                for id, c, q in zip(ids_to_crossmatch, catnorth_count, quaia_count)
            }
            with open(
                f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
                "r",
            ) as file:
                events_dict_add = json.load(file)
            for key, value in crossmatch_dict_stats.items():
                if key in events_dict_add:
                    events_dict_add[key]["crossmatch"] = value
                else:
                    logmessage = f"{key} not in events dictionary - couldnt add stats"
                    logger.log(logmessage, slack=False)
            if not self.testing:
                with open(
                    f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
                    "w",
                ) as file:
                    json.dump(events_dict_add, file)

            return catnorth, quaia


class FormatEventsToPublish:
    def __init__(self, path_data, github_token, observing_run, testing=False):
        self.path_data = path_data
        self.github_token = github_token
        self.observing_run = observing_run
        self.testing = testing

    def plot_trigger_timeline(self):
        # Load and preprocess the data
        trigger_df = pd.read_csv(
            f"{self.path_data}/events_summary/trigger.md",
            delimiter="|",
            skipinitialspace=True,
        ).iloc[:, 1:-1]
        trigger_df = trigger_df.iloc[1:]
        trigger_df.columns = [
            "graceids",
            "GW MJD",
            "90% Area (deg2)",
            "50% Area (deg2)",
            "Distance (Gpc)",
            "FAR (years/FA)",
            "Mass (M_sol)",
            "Chirp Mass (left edge)",
            "gcnids",
            "time",
            "probability",
            "start",
            "cadence",
            "comments",
        ]
        trigger_df["GW MJD"] = trigger_df["GW MJD"].str.strip().astype(int)
        dates = Time(trigger_df["GW MJD"], format="mjd").datetime
        trigger_df["GW Date"] = [date.strftime("%Y-%m-%d") for date in dates]
        trigger_df["Mass (M_sol)"] = trigger_df["Mass (M_sol)"].str.strip().astype(int)

        # Split the data into two subsets
        cutoff_date = Time("2025-02-01", format="iso").mjd
        df_before_cutoff = trigger_df[trigger_df["GW MJD"] <= cutoff_date]
        df_after_cutoff = trigger_df[trigger_df["GW MJD"] > cutoff_date]

        # Calculate subplot width fractions
        total_points = len(trigger_df)
        fraction_before = len(df_before_cutoff) / total_points
        fraction_after = len(df_after_cutoff) / total_points

        # Create subplots with proportional widths
        fig, (ax1, ax2) = plt.subplots(
            2,
            1,
            gridspec_kw={"height_ratios": [fraction_before, fraction_after]},
            figsize=(10, 6),
        )

        # Plot points for O4b

        ax1.scatter(
            df_before_cutoff["GW MJD"],
            [0.1] * len(df_before_cutoff),
            s=df_before_cutoff["Mass (M_sol)"] * 10,
            alpha=0.2,
            edgecolors="darkblue",
            linewidth=1,
        )
        ax1.set_yticks([])
        ax1.set_ylabel("O4b", fontsize=16)
        ax1.set_xticks(df_before_cutoff["GW MJD"])
        ax1.set_xticklabels(
            df_before_cutoff["GW Date"], rotation=45, ha="right", fontsize=12
        )
        ax1.spines["top"].set_visible(False)
        ax1.spines["right"].set_visible(False)
        ax1.spines["left"].set_visible(False)
        ax1.spines["bottom"].set_position("zero")
        ax1.set_ylim(0, 0.2)
        ax1.tick_params(axis="x", rotation=30)

        for i, row in df_before_cutoff.iterrows():
            if pd.notna(row["Chirp Mass (left edge)"]):
                ax1.annotate(
                    f"{row['Chirp Mass (left edge)'].strip()}M$_{{c}}$",
                    (row["GW MJD"], 0.1),
                    textcoords="offset points",
                    xytext=(0, -5),
                    ha="center",
                )
            else:
                ax1.annotate(
                    f"{row['Mass (M_sol)']}M$_{{\\odot}}$",
                    (row["GW MJD"], 0.1),
                    textcoords="offset points",
                    xytext=(0, -5),
                    ha="center",
                )

        # Plot points for O4c
        ax2.scatter(
            df_after_cutoff["GW MJD"],
            [0.1] * len(df_after_cutoff),
            s=df_after_cutoff["Mass (M_sol)"] * 10,
            alpha=0.2,
            edgecolors="darkblue",
            linewidth=1,
        )
        ax2.set_yticks([])
        ax2.set_xlabel("Date", fontsize=18)
        ax2.set_ylabel("O4c", fontsize=16)
        ax2.set_xticks(df_after_cutoff["GW MJD"])
        ax2.set_xticklabels(
            df_after_cutoff["GW Date"], rotation=45, ha="right", fontsize=12
        )
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
        ax2.spines["left"].set_visible(False)
        ax2.spines["bottom"].set_position("zero")
        ax2.set_ylim(0, 0.2)
        ax2.tick_params(axis="x", rotation=30)

        for i, row in df_after_cutoff.iterrows():
            if pd.notna(row["Chirp Mass (left edge)"]):
                ax2.annotate(
                    f"{row['Chirp Mass (left edge)'].strip()}M$_{{c}}$",
                    (row["GW MJD"], 0.1),
                    textcoords="offset points",
                    xytext=(0, -5),
                    ha="center",
                )
            else:
                ax2.annotate(
                    f"{row['Mass (M_sol)']}M$_{{\\odot}}$",
                    (row["GW MJD"], 0.1),
                    textcoords="offset points",
                    xytext=(0, -5),
                    ha="center",
                )
        plt.suptitle("Timeline of Triggered Observations", fontsize=20)
        plt.tight_layout()
        plt.show()

    def push_events(self):
        # get events from multiple runs (we present a single markdown file for trigger and error trigger)
        events_dict_add = {}
        # TODO: make a "maintenance" doc and note that new runids should be added as they start
        for rid in ["O4c", "O4b"]:  # runids for BBHBOT trigger operation
            file_path = f"{self.path_data}/flare_data/dicts/events_dict_{rid}.json"
            with open(file_path, "r") as file:
                events_dict_add.update(json.load(file))  # Combine dictionaries
        # get just events for the specified run
        file_path = (
            f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json"
        )
        with open(file_path, "r") as file:
            current_run_dict = json.load(file)
        current_run_ids = list(set(current_run_dict.keys()))
        # convert back to df
        restructured_dict = {
            key: {"graceids": key, **value["gw"]}
            for key, value in events_dict_add.items()
        }
        df_full = pd.DataFrame.from_dict(restructured_dict, orient="index")
        df_full = df_full.reset_index(drop=True)
        if "trigger plan" in df_full.columns:
            trigger_plan = json_normalize(df_full["trigger plan"])
            df_full = pd.concat([df_full, trigger_plan], axis=1)
        else:
            df_full["trigger plan"] = None
        # make gracids into links
        gracedbids = df_full["graceids"]
        gracedb_urls = [
            f"https://gracedb.ligo.org/superevents/{id}/view/" for id in gracedbids
        ]
        gracedb_links = [f"[{id}]({url})" for id, url in zip(gracedbids, gracedb_urls)]
        df_full["graceids"] = gracedb_links
        # make gcnids into links
        fritzids = df_full["gcnids"]
        fritz_urls = [f"https://fritz.science/gcn_events/{id}" for id in fritzids]
        fritz_links = [f"[{id}]({url})" for id, url in zip(fritzids, fritz_urls)]
        df_full["gcnids"] = fritz_links
        # put newest events at the top
        df_full = df_full.sort_values(by="GW MJD", ascending=False)
        df_full = df_full.reset_index(drop=True)
        # move Chirp Mass (left edge) to the right of Mass (M_sol)
        if "Chirp Mass (left edge)" in df_full.columns:
            chirp_mass = df_full.pop("Chirp Mass (left edge)")
            df_full.insert(
                df_full.columns.get_loc("Mass (M_sol)") + 1,
                "Chirp Mass (left edge)",
                chirp_mass,
            )
        # remove trigger_plan, gcnids
        df = df_full.drop(
            columns=[
                col
                for col in [
                    "trigger plan",
                    "gcnids",
                    "time",
                    "probability",
                    "start",
                    "cadence",
                ]
                if col in df_full.columns
            ]
        )
        # custom comments
        # TODO: make a comments dictionary that this draws instead of hardcoding here
        df["comments"] = ""
        df.loc[df["graceids"].str.contains("S240921cw"), "comments"] = "moon too close"
        df.loc[df["graceids"].str.contains("S241125n"), "comments"] = (
            "Swift/Bat coincident detection"
        )
        df.loc[df["graceids"].str.contains("S241130n"), "comments"] = "sun too close"
        df.loc[df["graceids"].str.contains("S250712cd"), "comments"] = (
            "serendipitous coverage"
        )

        # priority df
        df_priority = df[
            df["graceids"].str.contains("|".join(current_run_ids), na=False)
        ]
        df_priority = df_priority.drop(
            columns=[
                col
                for col in ["trigger plan", "cadence", "start"]
                if col in df_priority.columns
            ]
        )
        confident = df_priority[
            df_priority["FAR (years/FA)"] > 10
        ]  # FAR is in units of years per false alert
        high_mass = df_priority[
            (
                df_priority["Chirp Mass (left edge)"].notna()
                & (df_priority["Chirp Mass (left edge)"] >= 22)
            )
            | (
                df_priority["Chirp Mass (left edge)"].isna()
                & (df_priority["Mass (M_sol)"] > 60)
            )
        ]
        low_area = df_priority[df_priority["90% Area (deg2)"] < 1000]
        highmass_lowarea = pd.merge(high_mass, low_area)
        priority = pd.merge(highmass_lowarea, confident)
        logmessage = f"{len(priority)} {self.observing_run} events with FAR > 10 and mchirp>22 (mass > 60) and area < 1000 sq deg"
        logger.log(logmessage, slack=False)
        # #manual edits
        priority.loc[priority["GW MJD"] == 60572, "gcnids"] = (
            "[2024-09-19T06:15:59](https://fritz.science/gcn_events/2024-09-19T06:15:59)"
        )
        # #add comments
        # TODO: add to maintenance doc
        priority["comments"] = ""
        priority.loc[priority["graceids"].str.contains("S241210cw"), "comments"] = (
            "Sun too close"
        )
        priority.loc[priority["graceids"].str.contains("S241130n"), "comments"] = (
            "Sun too close"
        )
        priority.loc[priority["graceids"].str.contains("S241129aa"), "comments"] = (
            "Southern target"
        )
        priority.loc[priority["graceids"].str.contains("S240924a"), "comments"] = (
            "Southern target"
        )
        # remove nan gcnids
        priority["gcnids"] = priority["gcnids"].apply(
            lambda x: "" if isinstance(x, str) and "nan" in x else x
        )
        # trigger df
        trigger_df = df_full[df_full["trigger"] == "triggered"]
        trigger_df = trigger_df.drop(
            columns=[
                col for col in ["trigger", "trigger plan"] if col in trigger_df.columns
            ]
        )

        # manual edits
        trigger_df.loc[trigger_df["GW MJD"] == 60572, "gcnids"] = (
            "[2024-09-19T06:15:59](https://fritz.science/gcn_events/2024-09-19T06:15:59)"
        )
        # add comments
        trigger_df["comments"] = ""
        trigger_df.loc[trigger_df["graceids"].str.contains("S241125n"), "comments"] = (
            "Swift/Bat coincident detection"
        )
        trigger_df.loc[trigger_df["graceids"].str.contains("S250712cd"), "comments"] = (
            "serendipitious cov"
        )

        # trigger errors
        error_triggers = df_full[
            (df_full["trigger"] == "bad trigger")
            | (df_full["trigger"] == "missed trigger")
            | (df_full["trigger"] == "nan")
            | (df_full["trigger"] == "no plan")
            | (df_full["trigger"] == "no valid plan")
        ]
        error_triggers = error_triggers.drop(
            columns=[
                col
                for col in ["trigger", "trigger plan", "cadence"]
                if col in error_triggers.columns
            ]
        )

        # manual edits
        error_triggers.loc[error_triggers["GW MJD"] == 60573, "gcnids"] = (
            "[2024-09-20T07:34:24](https://fritz.science/gcn_events/2024-09-20T07:34:24)"
        )
        error_triggers.loc[error_triggers["GW MJD"] == 60568, "gcnids"] = (
            "[2024-09-15T10:51:51](https://fritz.science/gcn_events/2024-09-15T10:51:51)"
        )
        # add comments
        error_triggers["comments"] = "fails mass criteria"
        error_triggers["comments"] = "fails mass criteria"
        error_triggers.loc[error_triggers["GW MJD"] == 60694, "comments"] = (
            "plan has zero observations"
        )

        # now reduce df to just the current observing run
        df = df[df["graceids"].str.contains("|".join(current_run_ids), na=False)]

        # format to push to repo
        df = df.fillna("")
        priority = priority.fillna("")
        trigger_df = trigger_df.fillna("")
        error_triggers = error_triggers.fillna("")

        trigger_df["cadence"] = trigger_df["cadence"].apply(
            lambda dates: [date.replace("-", ".") for date in dates]
            if isinstance(dates, list)
            else dates
        )
        markdown_table = df.to_markdown(index=False)
        markdown_table_priority = priority.to_markdown(index=False)
        markdown_table_trigger = trigger_df.to_markdown(index=False)
        markdown_table_error_triggers = error_triggers.to_markdown(index=False)
        if not self.testing:
            os.makedirs(f"{self.path_data}/events_summary", exist_ok=True)
            files_to_write = {
                f"{self.path_data}/events_summary/{self.observing_run}.md": markdown_table,
                f"{self.path_data}/events_summary/{self.observing_run}_priority.md": markdown_table_priority,
                f"{self.path_data}/events_summary/trigger.md": markdown_table_trigger,
                f"{self.path_data}/events_summary/error_trigger.md": markdown_table_error_triggers,
            }
            for file_path, content in files_to_write.items():
                with open(file_path, "w") as f:
                    f.write(content)
            path_events_summary = f"{self.path_data}/events_summary"
            PublishToGithub(
                self.github_token, logger, testing=self.testing
            ).push_changes_to_repo(path_events_summary)

        return df, priority, trigger_df, error_triggers


class PlotSkymap:
    def __init__(self, gracedbid, path_data, observing_run, catalog="agn_catnorth"):
        self.gracedbid = gracedbid
        self.path_data = path_data
        self.observing_run = observing_run
        self.catalog = catalog
        self.g = GraceDb()

    def load_agn_crossmatches(self):
        with gzip.open(
            f"{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz",
            "rb",
        ) as f:
            crossmatch_dict = pickle.load(f)
            agn = crossmatch_dict[self.gracedbid][self.catalog]
            ra = [x["ra"] for x in agn]
            dec = [x["dec"] for x in agn]
            return ra, dec

    def get_moc(self):
        event_files = self.g.files(self.gracedbid).json()
        mocs = [k for k in list(event_files) if "multiorder" in k]
        if not mocs:
            url = "none"
            logmessage = f"Couldnt find MOC for {self.gracedbid}"
            logger.log(logmessage, slack=False)
        else:
            if any("LALInference" in item for item in mocs):
                mocs = [k for k in mocs if "LALInference" in k]
            key = [
                mocs
                if len(mocs) == 1
                else list(filter(lambda k: "2" in k, mocs))[0]
                if list(filter(lambda k: "2" in k, mocs))
                else list(filter(lambda k: "1" in k, mocs))[0]
                if list(filter(lambda k: "1" in k, mocs))
                else "LALInference.multiorder.fits"
                if "LALInference.multiorder.fits" in mocs
                else list(filter(lambda k: "0" in k, mocs))[0]
                if list(filter(lambda k: "0" in k, mocs))
                else mocs[0]
            ]

            url = event_files[key[0]]
            skymap = read_sky_map(url)[0]
            return skymap

    def plot(self, RA_unit="hours", show_contour=False, show_agn=True):
        """
        Plot skymaps

        Parameters
        ----------
        skymaps : list of skymaps
        RA_unit : unit for the right ascension, either hours or degrees
        """
        skymap = self.get_moc()
        plt.figure(figsize=(10, 5))
        if RA_unit == "degrees":
            ax = plt.axes(projection="astro degrees mollweide")
        elif RA_unit == "hours":
            ax = plt.axes(projection="astro hours mollweide")
        else:
            raise ValueError("Does not understand {}".format(RA_unit))
        ax.grid()
        ax.imshow_hpx(skymap, cmap="Blues")
        if show_contour:
            ax.contour_hpx(
                (
                    ligo.skymap.postprocess.util.find_greedy_credible_levels(skymap),
                    "ICRS",
                ),
                levels=[0.9],
                linewidths=1,
                nested=True,
                colors="blue",
            )
        if show_agn:
            ra, dec = self.load_agn_crossmatches()
            ax.plot(
                ra,
                dec,
                "o",
                color="orange",
                markersize=0.02,
                transform=ax.get_transform("world"),
            )
        plt.title(self.gracedbid)
        plt.show()


class VisualizePop:
    def __init__(self, path_data, observing_run):
        self.path_data = path_data
        self.observing_run = observing_run

    def plot_masses(self):
        # Ensure runid is a list for consistent processing
        if not isinstance(self.observing_run, list):
            self.observing_run = [self.observing_run]
        colors = ["#040348", "#FF5733", "#33FF57"]
        color_cycle = iter(colors)
        plt.figure(figsize=(10, 6))
        bin_edges = None
        stacked_heights = None
        for run in self.observing_run:
            try:
                # Load the events dictionary for the current runid
                with open(
                    f"{self.path_data}/flare_data/dicts/events_dict_{run}.json", "r"
                ) as file:
                    events_dict_add = json.load(file)
                # Extract masses
                masses = [
                    event["gw"]["Mass (M_sol)"]
                    for event in events_dict_add.values()
                    if "gw" in event and "Mass (M_sol)" in event["gw"]
                ]
                # Compute histogram data
                counts, bins = np.histogram(
                    masses, bins=30, range=(min(masses), max(masses))
                )
                # Initialize bin_edges and stacked_heights on the first iteration
                if bin_edges is None:
                    bin_edges = bins
                    stacked_heights = np.zeros_like(counts)
                color = next(
                    color_cycle,
                    np.random.rand(
                        3,
                    ),
                )  # Use predefined color or random if exhausted
                plt.bar(
                    bin_edges[:-1],
                    counts,
                    width=np.diff(bin_edges),
                    bottom=stacked_heights,
                    color=color,
                    edgecolor="black",
                    label=f"{run}",
                    align="edge",
                )
                stacked_heights += counts
            except FileNotFoundError:
                logmessage = f"File for runid {run} not found. Skipping."
                logger.log(logmessage, slack=False)
            except Exception as e:
                logmessage = f"Error processing runid {run}: {e}. Skipping."
                logger.log(logmessage, slack=False)
        plt.title("Significant BBH Mass Distribution", fontsize=20)
        plt.xlabel("Mass (M$_{\\odot}$)", fontsize=18)
        plt.ylabel("Count", fontsize=18)
        plt.tick_params(axis="both", which="major", labelsize=16)
        plt.legend(fontsize=14)
        plt.show()
