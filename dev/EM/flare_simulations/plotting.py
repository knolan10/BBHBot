import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from astropy.time import Time


class Plotter:
    def __init__(
        self,
        index_to_plot,
        color_to_plot,
        agn,
        rolling_stats,
        gw_date,
        eventid,
        simulation=False,
    ):
        self.index_to_plot = index_to_plot
        self.color_to_plot = color_to_plot
        self.agn = agn
        self.rolling_stats = rolling_stats
        self.gw_date = gw_date
        self.eventid = eventid
        self.simulation = simulation
        if self.simulation:
            self.agn = self.open_simulated_agn()
            self.color_to_plot = "g"  # enforce single color for simulated data

    def open_simulated_agn(self):
        data = np.load(self.agn, allow_pickle=True)
        mags = data["mags"]
        jds = data["jds"]
        # flare_jd = data['flare_jd']
        # if not flare_jd:
        #     flare_jd = len(mags) * ['none']
        AGN = [pd.DataFrame({"jd": jds, "mag": mag}) for mag in mags]
        return AGN

    def plot_all(self, index):
        agn_indexed = self.agn[index]
        rolling_stats_indexed = self.rolling_stats[index]
        if type(self.gw_date) is list:
            gw_date_indexed = self.gw_date[index]
        else:
            gw_date_indexed = self.gw_date
        if type(self.eventid) is list:
            eventid_indexed = self.eventid[index]
        else:
            eventid_indexed = self.eventid
        fig, axes = plt.subplots(1, 3, figsize=(12, 5))
        fig.suptitle(f"{eventid_indexed}", fontsize=18)
        colors = ["#77926f", "#c8aca9", "#cba560"]  # Colors for g, r, i filters
        titles = ["filter=g", "filter=r", "filter=i"]
        dateobs_mjd = round(Time(gw_date_indexed, format="jd").mjd)

        for i, ax in enumerate(axes):  # i represents each filter color
            ax.set_title(f"{titles[i]}, index = {index}", fontsize=15)

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
                    alpha=0.5,
                )
            ax.plot(
                baseline_times,
                baseline_medians,
                "X",
                color=colors[i],
                markersize=10,
                alpha=0.5,
            )

            # Plot GW window
            ax.axvspan(dateobs_mjd, dateobs_mjd + 200, color="#c5c9c7", alpha=0.7)

            # Plot points for rolling medians in GW
            gw_medians = rolling_stats_indexed[i][2]
            gw_times = [
                time - 2400000
                for time in rolling_stats_indexed[i][4][len(baseline_medians) :]
            ]  # MJD
            ax.plot(gw_times, gw_medians, "X", color="#fc2647", markersize=10)

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
        rolling_stats_indexed = self.rolling_stats[index]
        if type(self.gw_date) is list:
            gw_date_indexed = self.gw_date[index]
        else:
            gw_date_indexed = self.gw_date
        if type(self.eventid) is list:
            eventid_indexed = self.eventid[index]
        else:
            eventid_indexed = self.eventid
        dateobs_mjd = round(Time(gw_date_indexed, format="jd").mjd)
        if not self.simulation:
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
        else:
            curve = agn_indexed.copy()
            color = "#77926f"
        fig, ax = plt.subplots(figsize=(12, 5))
        fig.suptitle(f"{eventid_indexed}", fontsize=18)
        # Convert JD to MJD for plotting
        curve["mjd"] = curve["jd"].round() - 2400000
        if not self.simulation:
            # Group by MJD and plot weighted means for readability
            bin_size = 25
            curve["mjd_bin"] = (curve["mjd"] // bin_size) * bin_size
            grouped = curve.groupby("mjd_bin")
            weighted_means = grouped.apply(
                lambda g: np.average(g["mag"], weights=g["sigma_mag"])
            )
            mean_sigma_mag = grouped["sigma_mag"].mean()
            ax.plot(
                weighted_means.index, weighted_means, "o", color=color, markersize=3
            )
            ax.errorbar(
                weighted_means.index,
                weighted_means,
                yerr=mean_sigma_mag,
                fmt="none",
                ecolor=color,
                capsize=0,
            )
            # get medians
            baseline_medians = rolling_stats_indexed[i][0]
            baseline_times = [
                time - 2400000
                for time in rolling_stats_indexed[i][4][: len(baseline_medians)]
            ]  # MJD
            gw_medians = rolling_stats_indexed[i][2]
            gw_times = [
                time - 2400000
                for time in rolling_stats_indexed[i][4][len(baseline_medians) :]
            ]  # MJD
        else:
            ax.plot(curve["mjd"], curve["mag"], "o", color=color, markersize=3)
            # get medians
            baseline_medians = rolling_stats_indexed[0]
            baseline_times = [
                time - 2400000
                for time in rolling_stats_indexed[4][: len(baseline_medians)]
            ]  # MJD
            gw_medians = rolling_stats_indexed[2]
            gw_times = [
                time - 2400000
                for time in rolling_stats_indexed[4][len(baseline_medians) :]
            ]  # MJD
        # plot medians
        for j in range(len(baseline_medians)):
            ax.axhline(
                y=baseline_medians[j],
                color=color,
                linestyle="dashed",
                lw=0.75,
                alpha=0.5,
            )
        ax.plot(
            baseline_times, baseline_medians, "X", color=color, markersize=10, alpha=0.5
        )
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
        index = None  # Initialize i to ensure it is defined
        if self.index_to_plot == "all":
            for index in range(0, len(self.agn)):
                try:
                    if self.color_to_plot == "all":
                        self.plot_all(index)
                    else:
                        self.plot_single(index)
                except Exception as e:
                    print(e)
        elif isinstance(self.index_to_plot, list):
            for index in self.index_to_plot:
                try:
                    if self.color_to_plot == "all":
                        self.plot_all(index)
                    else:
                        self.plot_single(index)
                except Exception as e:
                    print(e)
        else:
            print("Invalid index to plot")
