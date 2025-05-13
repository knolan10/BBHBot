import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import gzip
import pickle
import json
import os
from scipy import stats
import math
from astropy.time import Time


class FlarePreprocessing:
    def __init__(self, graceid, path_data, observing_run="O4c"):
        self.graceid = graceid
        self.path_data = path_data
        self.path_photometry = f"{path_data}/flare_data/ZFPS/"
        self.observing_run = observing_run

    def load_event_lightcurves(self):
        # open the stored event info
        with gzip.open(
            f"{self.path_data}/flare_data/dicts/crossmatch_dict_{self.observing_run}.gz",
            "rb",
        ) as f:
            crossmatch_dict = pickle.load(f)
        coords = crossmatch_dict[self.graceid]["agn_catnorth"]
        name = [str(x["ra"]) + "_" + str(x["dec"]) for x in coords]
        path = self.path_photometry
        df = [
            pd.read_pickle(path + file + ".gz", compression="gzip")
            for file in name
            if os.path.exists(path + file + ".gz")
        ]
        coords = [file for file in name if os.path.exists(path + file + ".gz")]
        return df, coords

    def load_simulated_lightcurves(self):
        """
        open the simulated lightcurves
        """
        path = self.path_photometry
        df = [
            pd.read_pickle(path + file + ".gz", compression="gzip")
            for file in os.listdir(path)
        ]
        return df

    def get_total_fluxes(self, df):
        """
        see zfps sect. 6.5
        """
        df2 = df[df["dnearestrefsrc"] < 1]
        nearestrefflux = 10 ** (0.4 * (df2["zpdiff"] - df2["nearestrefmag"]))
        nearestreffluxunc = df2["nearestrefmagunc"] * nearestrefflux / 1.085
        Flux_tot = df2["forcediffimflux"] + nearestrefflux
        Fluxunc_tot = np.sqrt(
            df2["forcediffimfluxunc"] ** 2 + nearestreffluxunc**2
        )  # add variances (conservative estimate)
        SNR_tot = Flux_tot / Fluxunc_tot
        df2.insert(0, "SNR_tot", SNR_tot, False)
        df2.insert(0, "Flux_tot", Flux_tot, False)
        df2.insert(0, "Fluxunc_tot", Fluxunc_tot, False)
        return df2

    def get_calibrated_mags(self, df):
        SNT = 3  # Signal-to-Noise Threshold (for declaring significant detection)
        SNU = 5  # Signal-to-Noise Upper Limit (for assigning upper limit)
        # We have a "confident" detection; compute mag with error bar:
        df_conf = df[df["SNR_tot"] > SNT]
        mag = df_conf["zpdiff"] - 2.5 * np.log10(df_conf["Flux_tot"])
        sigma_mag = 1.0857 / df_conf["SNR_tot"]
        df_conf.insert(0, "mag", mag, False)
        df_conf.insert(0, "sigma_mag", sigma_mag, False)
        # calculate upper limit
        df_lim = df[df["SNR_tot"] < SNT]
        mag_lim = df_lim["zpdiff"] - 2.5 * np.log10(SNU * df_lim["Fluxunc_tot"])
        df_lim.insert(0, "mag_lim", mag_lim, False)
        return (df_conf, df_lim)

    def get_single_filter(self, filter, df):
        df_sf = df[(df["filter"] == filter)]
        return df_sf

    def process_for_flare(self):
        batch_photometry_filtered, radec = self.load_event_lightcurves()
        df_with_SNR = [self.get_total_fluxes(lc) for lc in batch_photometry_filtered]
        df_with_mag = [self.get_calibrated_mags(lc)[0] for lc in df_with_SNR]
        single_filter_g = [self.get_single_filter("ZTF_g", lc) for lc in df_with_mag]
        single_filter_r = [self.get_single_filter("ZTF_r", lc) for lc in df_with_mag]
        single_filter_i = [self.get_single_filter("ZTF_i", lc) for lc in df_with_mag]
        AGN = list(zip(single_filter_g, single_filter_r, single_filter_i, radec))
        print(f"found {len(AGN)} AGN")
        return AGN


# rolling window stats


class RollingWindowStats:
    def __init__(
        self,
        graceid,
        agn,
        path_data,
        window_size_before=50,
        window_size_after=25,
        baseline_years=2,
        observing_run="O4c",
    ):
        self.graceid = graceid
        self.agn = agn
        self.path_data = path_data
        self.window_size_before = window_size_before
        self.window_size_after = window_size_after
        self.baseline_years = baseline_years
        self.observing_run = observing_run

        # open the stored event info
        with open(
            f"{path_data}/flare_data/dicts/events_dict_{self.observing_run}.json", "r"
        ) as file:
            events_dict = json.load(file)
        self.dateobs = events_dict[self.graceid]["gw"]["GW MJD"] + 2400000.5

    def calculate_meds_mads(self, df):
        """
        this returns a list of where each item corresponds to an AGN
        with in each AGN there is a list of 3 items: stats for G,R,I filters
        within each filter there is a list of 3 items: medians, mads, jds
        """
        medians_pre = []
        mads_pre = []
        medians_post = []
        mads_post = []
        jds = []
        N_before = round(
            360 * self.baseline_years / self.window_size_before
        )  # number windows in baseline
        N_after = round(
            200 / self.window_size_after
        )  # number windows in 200 day post-GW period
        for i in range(N_before):
            start = self.dateobs - (i + 1) * self.window_size_before
            end = self.dateobs - i * self.window_size_before
            jd_mid = (start + end) / 2
            filtered_df = df[(df["jd"] >= start) & (df["jd"] < end)]
            if not filtered_df.empty:
                median_mag = filtered_df["mag"].median()
                mad_mag = stats.median_abs_deviation(filtered_df["mag"])
            else:
                median_mag = np.nan
                mad_mag = np.nan
            medians_pre.append(median_mag)
            mads_pre.append(mad_mag)
            jds.append(jd_mid)
        for i in range(N_after):
            start = self.dateobs + i * self.window_size_after
            end = self.dateobs + (i + 1) * self.window_size_after
            jd_mid = (start + end) / 2
            filtered_df = df[(df["jd"] >= start) & (df["jd"] < end)]
            if not filtered_df.empty:
                median_mag = filtered_df["mag"].median()
                mad_mag = stats.median_abs_deviation(filtered_df["mag"])
            else:
                median_mag = np.nan
                mad_mag = np.nan
            medians_post.append(median_mag)
            mads_post.append(mad_mag)
            jds.append(jd_mid)
        return medians_pre, mads_pre, medians_post, mads_post, jds

    def get_rolling_window_stats(self):
        gri_stats = []
        for agn in self.agn:
            stats_for_agn = [self.calculate_meds_mads(df) for df in agn[0:3]]
            gri_stats.append(stats_for_agn)
        return gri_stats

    def get_rolling_window_stats_simulated(self):
        """
        work with simulated data that does not specify color
        """
        stats = [self.calculate_meds_mads(df) for df in self.agn]
        return stats


# heuristic


class RollingWindowHeuristic:
    def __init__(
        self,
        graceid,
        agn,
        rolling_stats,
        path_data,
        percent=1,
        k_mad=3,
        testing=False,
        observing_run="O4c",
    ):
        self.graceid = graceid
        self.agn = agn
        self.rolling_stats = rolling_stats
        self.path_data = path_data
        self.percent = percent
        self.k_mad = k_mad
        self.testing = testing
        self.observing_run = observing_run

    def medians_test(self):
        """
        all medians post gw are brighter than x sigma of x % of baseline medians
        """
        # g
        stats_g = [i[0] for i in self.rolling_stats]
        index_g = [
            i
            for i in range(len(stats_g))
            if not (
                np.isnan(stats_g[i][0]).all()
                or np.isnan(stats_g[i][1]).all()
                or np.isnan(stats_g[i][2]).all()
            )
            and sum(
                x > np.nanmin(stats_g[i][2])
                for x in np.array(stats_g[i][0]) - self.k_mad * np.array(stats_g[i][1])
            )
            / len(stats_g[0])
            > self.percent
        ]
        # r
        stats_r = [i[1] for i in self.rolling_stats]
        index_r = [
            i
            for i in range(len(stats_r))
            if not (
                np.isnan(stats_r[i][0]).all()
                or np.isnan(stats_r[i][1]).all()
                or np.isnan(stats_r[i][2]).all()
            )
            and sum(
                x > np.nanmin(stats_r[i][2])
                for x in np.array(stats_r[i][0]) - self.k_mad * np.array(stats_r[i][1])
            )
            / len(stats_r[0])
            > self.percent
        ]
        # i
        stats_i = [i[2] for i in self.rolling_stats]
        index_i = [
            i
            for i in range(len(stats_i))
            if not (
                np.isnan(stats_i[i][0]).all()
                or np.isnan(stats_i[i][1]).all()
                or np.isnan(stats_i[i][2]).all()
            )
            and sum(
                x > np.nanmin(stats_i[i][2])
                for x in np.array(stats_i[i][0]) - self.k_mad * np.array(stats_i[i][1])
            )
            / len(stats_i[0])
            > self.percent
        ]
        print(
            f"in g,r,i we find {len(index_g)},{len(index_r)},{len(index_i)} candidates"
        )
        return index_g, index_r, index_i

    def flares_across_filters(self, g, r, i):
        """
        find detections in common between different colors
        """
        gr = np.intersect1d(g, r)
        print(f"{len(gr)} AGN have flares in g and r filters")
        gri = np.intersect1d(i, gr)
        print(f"{len(gri)} AGN have flares in g, r, and i filters")
        return gr, gri

    def check_photometry_coverage(self):
        def is_all_nan(lst):
            return all(math.isnan(x) for x in lst)

        input = len(self.agn)
        # cut from consideration bc no points in 200 day window post gw
        no_gw_points = [
            i
            for i in self.rolling_stats
            if is_all_nan(i[0][2]) and is_all_nan(i[1][2]) and is_all_nan(i[2][2])
        ]
        number_no_gw_points = len(no_gw_points)
        # cut from consideration bc no baseline points
        no_baseline_points = [
            i
            for i in self.rolling_stats
            if is_all_nan(i[0][0]) and is_all_nan(i[1][0]) and is_all_nan(i[2][0])
        ]
        number_no_baseline_points = len(no_baseline_points)
        print(
            number_no_gw_points,
            "/",
            input,
            "have no observations in any color in 200 day post GW period",
        )
        print(
            number_no_baseline_points,
            "/",
            input,
            "have no observations in any color before the GW detection",
        )
        return number_no_gw_points, number_no_baseline_points

    def get_flares(self):
        g, r, i = self.medians_test()
        unique_index = list(set(g + r + i))
        print(f"{len(unique_index)} unique flares across all colors")
        gr, gri = self.flares_across_filters(g, r, i)
        radec = [i[3] for i in self.agn]
        flare_coords_g = [radec[x] for x in g]
        flare_coords_r = [radec[x] for x in r]
        flare_coords_i = [radec[x] for x in i]

        number_no_gw_points, number_no_baseline_points = (
            self.check_photometry_coverage()
        )
        anomalous_dict = {
            self.graceid: {
                "catnorth_agn_with_photometry": len(self.agn),
                "no_baseline_points": number_no_baseline_points,
                "no_gw_points": number_no_gw_points,
                "number unique flares": len(unique_index),
                "number_g": len(g),
                "number_r": len(r),
                "number_i": len(i),
                "coords_g": flare_coords_g,
                "coords_r": flare_coords_r,
                "coords_i": flare_coords_i,
            }
        }

        if not self.testing:
            with open(
                f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
                "r",
            ) as file:
                events_dict_add = json.load(file)

        # add new values to flare key without replacing existing values
        for key, value in anomalous_dict.items():
            if key in events_dict_add:
                if "flare" in events_dict_add[key]:
                    events_dict_add[key]["flare"].update(value)
                else:
                    events_dict_add[key]["flare"] = value
        if not self.testing:
            with open(
                f"{self.path_data}/flare_data/dicts/events_dict_{self.observing_run}.json",
                "w",
            ) as file:
                json.dump(events_dict_add, file)

        # publish to public repo
        data = {
            "flare_coords_g": flare_coords_g,
            "flare_coords_r": flare_coords_r,
            "flare_coords_i": flare_coords_i,
        }
        directory = f"{self.path_data}/flares"
        if not self.testing:
            os.makedirs(directory, exist_ok=True)
            path = f"{directory}/{self.graceid}.json"
            with open(path, "w") as json_file:
                json.dump(data, json_file)

        return g, r, i, gr, gri


class Plotter:
    def __init__(
        self,
        index_to_plot,
        color_to_plot,
        agn,
        rolling_stats,
        graceid,
        path_data,
        observing_run="O4c",
        flares_from_graceid=False,
    ):
        self.index_to_plot = index_to_plot
        self.color_to_plot = color_to_plot
        self.agn = agn
        self.rolling_stats = rolling_stats
        self.graceid = graceid
        self.path_data = path_data
        self.observing_run = observing_run
        self.flares_from_graceid = flares_from_graceid

        # open the stored event info
        with open(
            f"{path_data}/flare_data/dicts/events_dict_{self.observing_run}.json", "r"
        ) as file:
            events_dict = json.load(file)
        self.dateobs = events_dict[self.graceid]["gw"]["GW MJD"] + 2400000.5

        if self.flares_from_graceid:
            flare_coords = events_dict[graceid]["flare"]
            coords = []
            # Collect coordinates based on the bands in flares_from_graceid
            if "g" in flares_from_graceid:
                coords.append(flare_coords.get("coords_g", []))
            if "r" in flares_from_graceid:
                coords.append(flare_coords.get("coords_r", []))
            if "i" in flares_from_graceid:
                coords.append(flare_coords.get("coords_i", []))
            # Find common values across all coordinate lists
            if coords:
                common_values = set(coords[0])  # Start with the first sublist
                for sublist in coords[1:]:
                    common_values &= set(sublist)  # Intersect with the next sublist
            else:
                common_values = set()  # Handle empty list of lists
            # Convert the result back to a list
            selected_flares = list(common_values)
            print(
                f"{len(selected_flares)} AGN have flares in {flares_from_graceid} band(s)"
            )
            # get indices for these flares
            all_AGN_coords = [agn[3] for agn in self.agn]
            flare_indices = [
                i for i, value in enumerate(all_AGN_coords) if value in selected_flares
            ]
            self.index_to_plot = [flare_indices[self.index_to_plot[0]]]

    def plot_all(self, index):
        agn_indexed = self.agn[index]
        if self.rolling_stats:
            rolling_stats_indexed = self.rolling_stats[index]
        if isinstance(self.dateobs, list):
            gw_date_indexed = self.dateobs[index]
        else:
            gw_date_indexed = self.dateobs
        if isinstance(self.graceid, list):
            eventid_indexed = self.graceid[index]
        else:
            eventid_indexed = self.graceid
        fig, axes = plt.subplots(1, 3, figsize=(12, 5))
        fig.suptitle(f"{eventid_indexed} ({agn_indexed[3]})", fontsize=18)
        colors = ["#77926f", "#c8aca9", "#cba560"]  # Colors for g, r, i filters
        titles = ["filter=g", "filter=r", "filter=i"]
        dateobs_mjd = round(Time(gw_date_indexed, format="jd").mjd)

        for i, ax in enumerate(axes):  # i represents each filter color
            ax.set_title(f"{titles[i]}", fontsize=15)

            curve = agn_indexed[i].copy()

            # Convert JD to MJD for plotting
            curve["mjd"] = curve["jd"].round() - 2400000
            # Group by MJD and plot weighted means for readability
            bin_size = 25
            curve["mjd_bin"] = (curve["mjd"] // bin_size) * bin_size
            grouped = curve.groupby("mjd_bin")
            weighted_means = grouped.apply(
                lambda g: np.average(g["mag"], weights=g["sigma_mag"])
            )
            mean_sigma_mag = grouped["sigma_mag"].mean()
            ax.plot(
                weighted_means.index, weighted_means, "o", color=colors[i], markersize=3
            )
            ax.errorbar(
                weighted_means.index,
                weighted_means,
                yerr=mean_sigma_mag,
                fmt="none",
                ecolor=colors[i],
                capsize=0,
            )

            # Plot horizontal line through each median in rolling window
            if self.rolling_stats:
                baseline_medians = rolling_stats_indexed[i][0]
                baseline_times = [
                    time - 2400000
                    for time in rolling_stats_indexed[i][4][: len(baseline_medians)]
                ]  # MJD
                for j in range(len(baseline_medians)):
                    ax.axhline(
                        y=baseline_medians[j],
                        color=colors[i],
                        linestyle="dashed",
                        lw=0.75,
                    )
                    ax.plot(
                        baseline_times,
                        baseline_medians,
                        "o",
                        color=colors[i],
                        markersize=5,
                    )
                # Plot points for rolling medians in GW
                gw_medians = rolling_stats_indexed[i][2]
                gw_times = [
                    time - 2400000
                    for time in rolling_stats_indexed[i][4][len(baseline_medians) :]
                ]  # MJD
                ax.plot(gw_times, gw_medians, "X", color="#fc2647", markersize=10)

            # Plot GW window
            ax.axvspan(dateobs_mjd, dateobs_mjd + 200, color="#c5c9c7", alpha=0.7)

            ax.invert_yaxis()
            ax.set_xlabel("MJD", fontsize=15)
            if i == 0:
                ax.set_ylabel("Magnitude", fontsize=15)

            x_ticks = ax.get_xticks()
            ax.set_xticks(x_ticks)
            ax.set_xticklabels(["{:.0f}".format(tick) for tick in x_ticks])

        plt.tight_layout()
        plt.show()

    def plot_single(self, index):
        agn_indexed = self.agn[index]
        if self.rolling_stats:
            rolling_stats_indexed = self.rolling_stats[index]
        if isinstance(self.gw_date, list):
            gw_date_indexed = self.dateobs[index]
        else:
            gw_date_indexed = self.dateobs
        if isinstance(self.eventid, list):
            eventid_indexed = self.graceid[index]
        else:
            eventid_indexed = self.graceid
        dateobs_mjd = round(Time(gw_date_indexed, format="jd").mjd)
        if self.color_to_plot == "g":
            i = 0
        elif self.color_to_plot == "r":
            i = 1
        elif self.color_to_plot == "i":
            i = 2
        else:
            print("Invalid color")
            return
        curve = agn_indexed[i].copy()
        color = ["#77926f", "#c8aca9", "#cba560"][i]  # Colors for g, r, i filters

        fig, ax = plt.subplots(figsize=(12, 5))
        fig.suptitle(f"{eventid_indexed} ({agn_indexed[3]})", fontsize=18)
        # Convert JD to MJD for plotting
        curve["mjd"] = curve["jd"].round() - 2400000
        # Group by MJD and plot weighted means for readability
        bin_size = 25
        curve["mjd_bin"] = (curve["mjd"] // bin_size) * bin_size
        grouped = curve.groupby("mjd_bin")
        weighted_means = grouped.apply(
            lambda g: np.average(g["mag"], weights=g["sigma_mag"])
        )
        mean_sigma_mag = grouped["sigma_mag"].mean()
        ax.plot(weighted_means.index, weighted_means, "o", color=color, markersize=3)
        ax.errorbar(
            weighted_means.index,
            weighted_means,
            yerr=mean_sigma_mag,
            fmt="none",
            ecolor=color,
            capsize=0,
        )
        if self.rolling_stats:
            # Plot horizontal line through each median in rolling window
            baseline_medians = rolling_stats_indexed[i][0]
            baseline_times = [
                time - 2400000
                for time in rolling_stats_indexed[i][4][: len(baseline_medians)]
            ]  # MJD
            for j in range(len(baseline_medians)):
                ax.axhline(
                    y=baseline_medians[j], color=color, linestyle="dashed", lw=0.75
                )
                ax.plot(
                    baseline_times, baseline_medians, "o", color=color, markersize=5
                )
            # Plot points for rolling medians in GW
            gw_medians = rolling_stats_indexed[i][2]
            gw_times = [
                time - 2400000
                for time in rolling_stats_indexed[i][4][len(baseline_medians) :]
            ]  # MJD
            ax.plot(gw_times, gw_medians, "X", color="#fc2647", markersize=10)
        # Plot GW window
        ax.axvspan(dateobs_mjd, dateobs_mjd + 200, color="#c5c9c7", alpha=0.7)

        # axes
        ax.invert_yaxis()
        ax.set_xlabel("MJD", fontsize=15)
        if i == 0:
            ax.set_ylabel("Magnitude", fontsize=15)
        plt.show()

    def show_plots(self):
        if self.index_to_plot == "all":
            for i in range(0, len(self.agn)):
                try:
                    if self.color_to_plot == "all":
                        self.plot_all(i)
                    else:
                        self.plot_single(i)
                except Exception as e:
                    print(e)
                    print(i)
        elif isinstance(self.index_to_plot, list):
            for i in self.index_to_plot:
                try:
                    if self.color_to_plot == "all":
                        self.plot_all(i)
                    else:
                        self.plot_single(i)
                except Exception as e:
                    print(e)
                    print(i)
        else:
            print("Invalid index to plot")
