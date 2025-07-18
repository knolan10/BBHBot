import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats
import os
import matplotlib.gridspec as gridspec
import matplotlib.colors as mcolors
import matplotlib.cm as cm
from sklearn.metrics import ConfusionMatrixDisplay
import itertools
from matplotlib import rcParams

rcParams["font.family"] = "Liberation Serif"


class SimulateFlaringAGN:
    def __init__(self, total_num_sim=None, verbose=False):
        self.total_num_sim = total_num_sim
        self.verbose = verbose

    def show_sim_table(self):
        data = {
            "Exp.": [0, 1, 2, 3],
            "Total # Sim.": [1300, 1300, 1300, 1300],
            "# Param Combos.": [130, 130, 130, 130],
            "AGN Characteristics": [
                "130 parameter combos interpolated from paper",
                "130 parameter combos interpolated from paper",
                "13 values from Graham 2017",
                "13 values from Graham 2017",
            ],
            "Flare Characteristics": [
                "No flare added",
                "JD 2460187-2460232, rise 30 days, decay 50 days, amplitude 0.2 mag",
                "For each of 13 AGN, 10 different flares added with amplitudes 0.1-1.0 mag, rise=30 and decay=50 days",
                "For each of 13 AGN, 10 different flares added with rise times 10-100 days, decay=50 days, amplitude 0.2 mag",
            ],
            "Data Format": [
                "There are 130 AGN DRW parameter combos. The first 10 AGN are from the first combo, next 10 are from the second combo, up to the 130th combo",
                "AGN same as above. Flares are all the same for each AGN, apart from random start times within a window",
                "first 100 AGN are all simulated from the first DRW parameter combo, next 100 are from the second combo, up to the 13th combo. first 10 flares have first flare mag, next 10 have second flare mag, up to 10th flare mag, and then we start over for the new AGN",
                "AGN same as above. first 10 flares have first flare rise time, next 10 have second flare rise time, up to 10th flare rise_time, and then we start over for the new AGN",
            ],
        }
        df = pd.DataFrame(data)
        print(df.to_markdown(index=False))

    def getDRWMag(self, tau, amp, mag, dt):
        loc = mag * np.exp(-dt / tau)
        scale = np.sqrt(amp * (1.0 - np.exp(-2.0 * dt / tau)))
        return loc + np.random.normal(0.0, scale)

    def generateDRW(self, t, tau, xmean, amp, burn=10000):
        # Generate in rest frame
        n = len(t)
        dt = np.diff(t)
        mag = np.zeros(n)
        mag[0] = np.random.normal(0, amp / np.sqrt(2.0))
        for i in range(burn):
            mag[0] = self.getDRWMag(tau, amp, mag[0], dt[np.random.randint(n - 1)])
        for i in range(n - 1):
            mag[i + 1] = self.getDRWMag(tau, amp, mag[i], dt[i])
        return xmean + mag

    def generate_flare(self, rise_t, decay_t, a):
        """
        generate bbh flare gaussian rise exponential decay
        """
        t_1 = np.arange(0, rise_t)
        g = a * np.e ** (-1 * (t_1 - rise_t) ** 2 / (2 * (rise_t) ** 2))
        t_2 = np.arange((rise_t + 1), (rise_t + 1 + decay_t))
        f = a * np.e ** (-1 * (t_2 - (rise_t + 1)) / decay_t)
        t = np.arange(0, (rise_t + decay_t))
        flare = np.concatenate((g, f), axis=0)
        return (t, flare)

    def get_lc(self, t, agn, flare):
        """
        add flare to randomly selected time within section at tail of agn signal
        """
        end = t + len(flare[0])
        before = agn[:t]
        signal = agn[t:end] - flare[1]
        after = agn[end - 1 :]
        agn_with_flare = np.concatenate((before, signal, after), axis=0)
        return agn_with_flare

    def ztf_observation_cadence(self):
        """
        sample lc signal to represent stochatic measurement and yearly periodicity of ztf observations
        """
        yearly_cadence = np.array(
            [
                np.arange(182, 365),
                np.arange(547, 730),
                np.arange(912, 1095),
                np.arange(1277, 1460),
                np.arange(1642, 1825),
                np.arange(2007, 2190),
            ]
        )
        observation_indices = np.concatenate(
            [
                np.unique(np.sort(np.random.choice(index, 60)))
                for index in yearly_cadence
            ]
        )
        observation_jds = np.arange(2458192, (2190 + 2458192))[observation_indices]
        return observation_indices, observation_jds

    def get_agn_drw_params(self, num_agn_interpolate, plot=False):
        """
        fit Graham 2017 parameter values with curve to get larger set of plausible parameter inputs
        Understanding extreme quasar optical variability with CRTS: I. Major AGN flares
        https://arxiv.org/pdf/1706.03079
        """
        # [mean magnitude, log characteristic timescale(tau), log sigma squared (amp)] from Graham 2017
        agn = [
            [14.25, 1.966, -2.422],
            [14.75, 2.186, -2.531],
            [15.25, 2.16, -2.494],
            [15.75, 2.375, -2.314],
            [16.25, 2.535, -2.339],
            [16.75, 2.613, -2.225],
            [17.25, 2.753, -2.137],
            [17.75, 2.798, -2.047],
            [18.25, 2.794, -2.018],
            [18.75, 2.704, -1.938],
            [19.25, 2.58, -1.758],
            [19.75, 2.409, -1.611],
            [20.25, 2.221, -1.602],
        ]
        # fit curve to get more plausible points from AGN paper parameters
        mag_fit = np.concatenate([[i[0]] for i in agn])
        amp_fit = np.concatenate([[10 ** i[2]] for i in agn])
        tau_fit = np.concatenate([[10 ** i[1]] for i in agn])
        z1 = np.polyfit(mag_fit, amp_fit, 4)
        f1 = np.poly1d(z1)
        z2 = np.polyfit(mag_fit, tau_fit, 5)
        f2 = np.poly1d(z2)
        agn = list(zip(mag_fit, tau_fit, amp_fit))
        if num_agn_interpolate:
            mag_new = np.linspace(mag_fit[0], mag_fit[-1], num_agn_interpolate)
            amp_new = f1(mag_new)
            tau_new = f2(mag_new)
            agn = list(zip(mag_new, tau_new, amp_new))
        if self.verbose:
            print(f"getting {len(agn)} agn parameter combinations")
        if plot:
            self.plot_drw_params(mag_new, amp_new, mag_fit, amp_fit, tau_new, tau_fit)
        if self.total_num_sim:
            if self.total_num_sim % len(agn) != 0:
                raise ValueError(
                    f"total_num_sim must be a multiple of {len(agn)}, the number of agn parameter combinations"
                )
            num_duplicate_agn = self.total_num_sim // len(agn)
            if self.verbose:
                print(f"duplicating each agn {num_duplicate_agn} times")
            agn = [x for x in agn for _ in range(num_duplicate_agn)]
        if self.verbose:
            print(f"getting {len(agn)} total agn")
        return agn

    def plot_drw_params(self, mag_new, amp_new, mag_fit, amp_fit, tau_new, tau_fit):
        """
        visualize the relationship between AGN DRW model parameters
        """
        fig, axs = plt.subplots(1, 2, figsize=(7, 3))
        fig.tight_layout()
        plt.subplots_adjust(wspace=0.25)
        axs[0].plot(mag_new, amp_new, "bo", markersize=5)
        axs[0].plot(mag_fit, amp_fit, "go", markersize=5)
        axs[0].set_xlabel("Mag")
        axs[0].set_ylabel("Amplitude (sigma squared, not log)")
        axs[1].plot(mag_new, tau_new, "bo", markersize=5)
        axs[1].plot(mag_fit, tau_fit, "go", markersize=5)
        axs[1].set_xlabel("Mag")
        axs[1].set_ylabel("Characteristic Timescale (tau, not log)")
        plt.show()

    def save_simulated_agn(self, file, mag, jd, flare):
        np.savez(
            os.path.join("../data/simulated_agn/", file),
            mags=mag,
            jds=jd,
            flare_jd=flare,
        )

    def simulate(
        self,
        num_agn_interpolate=False,
        num_flares_interpolate=None,
        flare_mag=False,
        flare_rise=False,
        flare_decay=False,
        plot=False,
        save_filename=None,
    ):
        """
        simulate AGN DRW
        From times series 0-2190 days (or JD=2458192-2460382), we assign the GW event to time=1985 (JD=2460177)
        We randomly start the flare rise between 1995-2038 days (JD=2460187-2460230)
        """
        agn_params = self.get_agn_drw_params(
            num_agn_interpolate=num_agn_interpolate, plot=plot
        )
        drw = [
            self.generateDRW(t=np.arange(0, 2190), tau=i[1], xmean=i[0], amp=i[2])
            for i in agn_params
        ]
        if not num_agn_interpolate:
            num_repeated_sequence_agn = self.total_num_sim / 13
        else:
            num_repeated_sequence_agn = self.total_num_sim / num_agn_interpolate
        flare_start_time_jd = []  # placeholder or default if no flare is added
        # add flare
        if flare_mag or flare_rise or flare_decay:
            if num_flares_interpolate:
                if not isinstance(
                    flare_mag, list
                ):  # repeat the single value for the number of unique values we should get
                    flare_mag = [flare_mag] * num_flares_interpolate
                else:  # get a sequence of values between the min and max provided in a list
                    flare_mag = [
                        round(x, 2)
                        for x in np.linspace(
                            flare_mag[0], flare_mag[1], num_flares_interpolate
                        )
                    ]
                if not isinstance(flare_rise, list):
                    flare_rise = [flare_rise] * num_flares_interpolate
                else:
                    flare_rise = [
                        round(x)
                        for x in np.linspace(
                            flare_rise[0], flare_rise[1], num_flares_interpolate
                        )
                    ]
                if not isinstance(flare_decay, list):
                    flare_decay = [flare_decay] * num_flares_interpolate
                else:
                    flare_decay = [
                        round(x)
                        for x in np.linspace(
                            flare_decay[0], flare_decay[1], num_flares_interpolate
                        )
                    ]
                flare = [
                    self.generate_flare(i, j, k)
                    for i, j, k in zip(flare_rise, flare_decay, flare_mag)
                ]  # get unique flare sequence
                if self.verbose:
                    print(f"getting {len(flare)} unique flares")
                num_duplicate_flare = int(num_repeated_sequence_agn / len(flare))
                if self.verbose:
                    print(
                        f"getting {num_duplicate_flare} sequential duplicates of each flare"
                    )
                flare = [x for x in flare for _ in range(num_duplicate_flare)]
                if self.verbose:
                    print(
                        f"repeating full flare sequence {int(self.total_num_sim / len(flare))} times"
                    )
                flare = flare * int(
                    self.total_num_sim / len(flare)
                )  # repeat flare sequence for total number of sim agn
            else:
                flare = [
                    self.generate_flare(flare_rise, flare_decay, flare_mag)
                ] * self.total_num_sim

            if len(flare) != self.total_num_sim:
                raise ValueError("length of flare parameters must equal total_num_sim")

            times = np.arange(0, 2190)
            flare_start_time = [
                round(np.random.choice(times[-195:-151]))
                for _ in range(self.total_num_sim)
            ]
            flare_start_time_jd = [x + 2458192 for x in flare_start_time]
            drw = [
                self.get_lc(i, j, k) for i, j, k in zip(flare_start_time, drw, flare)
            ]

        observation_indices, observation_jds = self.ztf_observation_cadence()
        ztf_sampled_agn = [lc[observation_indices] for lc in drw]

        if save_filename:
            self.save_simulated_agn(
                save_filename, ztf_sampled_agn, observation_jds, flare_start_time_jd
            )

        return ztf_sampled_agn, observation_jds, flare_start_time_jd


# rolling window stats


class RollingWindow:
    def __init__(self, agn_path, baseline_years=2, gw_jd=2460177):
        self.agn_path = agn_path
        self.baseline_years = baseline_years
        self.gw_jd = gw_jd

    def open_simulated_agn(self):
        data = np.load(self.agn_path, allow_pickle=True)
        mags = data["mags"]
        jds = data["jds"]
        # flare_jd = data['flare_jd']
        # if not flare_jd:
        #     flare_jd = len(mags) * ['none']
        AGN = [pd.DataFrame({"jd": jds, "mag": mag}) for mag in mags]
        return AGN

    def calculate_meds_mads(self, df, window_size_before, window_size_after):
        medians_pre = []
        mads_pre = []
        medians_post = []
        mads_post = []
        jds = []
        N_before = round(
            360 * self.baseline_years / window_size_before
        )  # number windows in baseline
        N_after = round(
            200 / window_size_after
        )  # number windows in 200 day post-GW period
        for i in range(N_before):
            start = self.gw_jd - (i + 1) * window_size_before
            end = self.gw_jd - i * window_size_before
            jd_mid = (start + end) / 2

            filtered_df = df[(df["jd"] >= start) & (df["jd"] < end)]
            median_mag = filtered_df["mag"].median()
            mad_mag = stats.median_abs_deviation(filtered_df["mag"])
            medians_pre.append(median_mag)
            mads_pre.append(mad_mag)
            jds.append(jd_mid)
        for i in range(N_after):
            start = self.gw_jd + i * window_size_after
            end = self.gw_jd + (i + 1) * window_size_after
            jd_mid = (start + end) / 2
            filtered_df = df[(df["jd"] >= start) & (df["jd"] < end)]
            median_mag = filtered_df["mag"].median()
            mad_mag = stats.median_abs_deviation(filtered_df["mag"])
            medians_post.append(median_mag)
            mads_post.append(mad_mag)
            jds.append(jd_mid)
        return medians_pre, mads_pre, medians_post, mads_post, jds

    def get_rolling_window_stats(self, window_size_before=50, window_size_after=25):
        AGN = self.open_simulated_agn()
        gri_stats = [
            self.calculate_meds_mads(df, window_size_before, window_size_after)
            for df in AGN
        ]
        return gri_stats


# heuristic


class RollingWindowHeuristic:
    def __init__(self, rolling_stats, percent=1, k_mad=3, num_gw_windows="ALL"):
        self.rolling_stats = rolling_stats
        self.percent = percent
        self.k_mad = k_mad
        self.num_gw_windows = num_gw_windows
        if self.num_gw_windows == "ALL":
            self.num_gw_windows = len(self.rolling_stats[0][0])

    def medians_test(self):
        """
        all medians post gw are brighter than x sigma of x % of baseline medians
        """
        index = [
            i
            for i in range(len(self.rolling_stats))
            if not (
                np.isnan(self.rolling_stats[i][0]).all()
                or np.isnan(self.rolling_stats[i][1]).all()
                or np.isnan(self.rolling_stats[i][2]).all()
            )
            and sum(
                x > np.nanmin(self.rolling_stats[i][2][0 : self.num_gw_windows])
                for x in np.array(self.rolling_stats[i][0])
                - self.k_mad * np.array(self.rolling_stats[i][1])
            )
            / len(self.rolling_stats[0])
            > self.percent
        ]
        return index


# vis


class PlotSimResults:
    def __init__(self, flares=None, title=None):
        self.flares = flares
        self.title = title
        self.SimulatorInstance = SimulateFlaringAGN()

    def percentage_passed(self, simulated_set, num_sequential_repeats=10):
        """
        For a given set of AGN simulated from the same values, calculate the percentage of AGN that passed heuristic.
        """
        max_value = max(simulated_set)
        fraction_passed = []
        for start in range(0, max_value + 1, num_sequential_repeats):
            end = start + num_sequential_repeats - 1
            count_in_range = sum(1 for x in simulated_set if start <= x <= end)
            fraction = count_in_range / num_sequential_repeats
            fraction_passed.append(fraction)
        return fraction_passed

    def retrieve_simulation_results(self):
        """
        This is written specifically for the simulations I have, so would need to be modified for other simulations.
        """
        agn_params = SimulateFlaringAGN(total_num_sim=1300).get_agn_drw_params(
            num_agn_interpolate=130
        )
        agn_mags = sorted(list(set([x[0] for x in agn_params])))
        agn_mags_original = [
            14.25,
            14.75,
            15.25,
            15.75,
            16.25,
            16.75,
            17.25,
            17.75,
            18.25,
            18.75,
            19.25,
            19.75,
            20.25,
        ]
        flare_mags = [round(x, 2) for x in np.linspace(0.1, 1.0, 10)]
        flare_rise_time = [round(x, 2) for x in np.linspace(10, 100, 10)]
        return agn_mags, agn_mags_original, flare_mags, flare_rise_time

    def plot_results(self):
        flare0_passed = self.percentage_passed(self.flares[0])
        flare1_passed = self.percentage_passed(self.flares[1])
        flare2_passed = self.percentage_passed(self.flares[2])
        flare3_passed = self.percentage_passed(self.flares[3])

        agn_mags, agn_mags_original, flare_mags, flare_rise_time = (
            self.retrieve_simulation_results()
        )

        fig = plt.figure(figsize=(10, 6.5))
        gs = gridspec.GridSpec(3, 2, height_ratios=[1, 1, 6])

        plt.subplots_adjust(hspace=1.5, wspace=0.7)
        fig.tight_layout()

        axs0 = plt.subplot(gs[0, :])  # First subplot, first row, spans both columns
        axs1 = plt.subplot(gs[1, :])  # Second subplot, second row, spans both columns
        axs2 = plt.subplot(gs[2, 0])  # Third subplot, third row, first column
        axs3 = plt.subplot(gs[2, 1])  # Fourth subplot, third row, second column

        fig.tight_layout()
        plt.subplots_adjust(hspace=0.35, wspace=0.2)

        # Normalize the flare0_passed values to [0, 1]
        norm = mcolors.Normalize(vmin=0, vmax=1)
        cmap = cm.inferno

        for x in np.arange(0, 130):
            color = cmap(norm(flare0_passed[x]))
            axs0.plot(agn_mags[x], 0, "s", color=color, markersize=18)
            axs0.get_yaxis().set_visible(False)
            axs0.set_xlabel("AGN Mag (no flare added)")
            axs0.spines["top"].set_visible(False)
            axs0.spines["right"].set_visible(False)
            axs0.spines["left"].set_visible(False)

            color = cmap(norm(flare1_passed[x]))
            axs1.plot(agn_mags[x], 0, "s", color=color, markersize=18)
            axs1.get_yaxis().set_visible(False)
            axs1.set_xlabel("AGN Mag (0.2 Mag flare added)")
            axs1.spines["top"].set_visible(False)
            axs1.spines["right"].set_visible(False)
            axs1.spines["left"].set_visible(False)

        for i, x in enumerate(agn_mags_original):
            # Get the next ten values for flare2_passed starting from index i*10
            color_values = flare2_passed[i * 10 : (i + 1) * 10]
            for j, color_value in enumerate(color_values):
                color = cmap(norm(color_value))
                axs2.plot(x, flare_mags[j], "s", color=color, markersize=24)
            axs2.set_xlabel("AGN magnitude")
            axs2.set_ylabel("Flare amplitude")
            axs2.spines["top"].set_visible(False)
            axs2.spines["right"].set_visible(False)

            # Get the next ten values for flare2_passed starting from index i*10
            color_values = flare3_passed[i * 10 : (i + 1) * 10]
            for j, color_value in enumerate(color_values):
                color = cmap(norm(color_value))
                axs3.plot(x, flare_rise_time[j], "s", color=color, markersize=24)
            axs3.set_xlabel("AGN magnitude")
            axs3.set_ylabel("Flare rise time")
            axs3.spines["top"].set_visible(False)
            axs3.spines["right"].set_visible(False)

        # Add a colorbar to the right of the figure, vertically
        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(
            sm,
            ax=[axs0, axs1, axs2, axs3],
            orientation="vertical",
            fraction=0.02,
            pad=0.04,
        )
        cbar.set_label("Fraction Passed by Heuristic", size=15)

        fig.suptitle(self.title, fontsize=15)
        plt.show()

    def plot_confusion_matrix(self):
        no_flare_indices = np.arange(0, 1300)
        flare_indices = np.arange(0, 1300)
        misclassified_as_flare = self.flares[0]
        correctly_classified_flare = self.flares[1]

        # Calculate counts
        true_negatives = len(no_flare_indices) - len(misclassified_as_flare)
        false_positives = len(misclassified_as_flare)
        false_negatives = len(flare_indices) - len(correctly_classified_flare)
        true_positives = len(correctly_classified_flare)

        # Construct confusion matrix
        cm = np.array(
            [[true_negatives, false_positives], [false_negatives, true_positives]]
        )

        # Normalize the confusion matrix by the total number of samples and convert to percentages
        cm_normalized = np.round(
            cm.astype("float") / cm.sum(axis=1)[:, np.newaxis] * 100
        ).astype(int)

        # Set font size for labels
        plt.rcParams.update({"font.size": 14})

        # Display confusion matrix with percentages
        disp = ConfusionMatrixDisplay(
            confusion_matrix=cm_normalized, display_labels=["No Flare", "Flare"]
        )
        disp.plot(cmap=plt.cm.Blues, values_format="d")

        # Modify the text annotations to include the percentage symbol
        for i in range(cm_normalized.shape[0]):
            for j in range(cm_normalized.shape[1]):
                disp.ax_.texts[i * cm_normalized.shape[1] + j].set_text(
                    f"{cm_normalized[i, j]}%"
                )

        plt.title("Confusion Matrix for Flare Detection")
        plt.show()

    def plot_pp(self):
        flare0_passed = self.percentage_passed(self.flares[0])
        flare1_passed = self.percentage_passed(self.flares[1])
        flare2_passed = self.percentage_passed(self.flares[2])
        flare3_passed = self.percentage_passed(self.flares[3])

        fig, axs = plt.subplots(2, 2, figsize=(10, 8))
        fig.suptitle("P-P Plots for Flare Passed Percentages", fontsize=20)

        # Function to create P-P plot
        def pp_plot(ax, data, title):
            data_sorted = np.sort(data)
            theoretical_quantiles = np.linspace(0, 1, len(data_sorted))
            empirical_quantiles = np.cumsum(data_sorted) / np.sum(data_sorted)
            ax.plot(theoretical_quantiles, empirical_quantiles, "o", markersize=5)
            ax.plot([0, 1], [0, 1], "r--")  # 45-degree line
            ax.set_title(title)
            ax.set_xlabel("Theoretical Quantiles")
            ax.set_ylabel("Empirical Quantiles")

        pp_plot(axs[0, 0], flare0_passed, "Simulation 0 Passed")
        pp_plot(axs[0, 1], flare1_passed, "Simulation 1 Passed")
        pp_plot(axs[1, 0], flare2_passed, "Simulation 2 Passed")
        pp_plot(axs[1, 1], flare3_passed, "Simulation 3 Passed")

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        plt.show()

    def plot_window_grid(self, count, win_pre, win_post, title=None):
        """
        experiment with window size
        """
        fig = plt.figure(figsize=(6, 5))
        ax1 = fig.add_subplot(111)

        window_combinations = itertools.product(win_pre, win_post)
        x, y = zip(*list(window_combinations))
        scatter = ax1.scatter(x, y, marker="s", c=count, s=1900, cmap="Blues")
        ax1.set_xlabel("Window size pre GW (days)")
        ax1.set_ylabel("Window size post GW (days)")

        ax1.spines["top"].set_visible(False)
        ax1.spines["right"].set_visible(False)

        fig.legend(
            *scatter.legend_elements(num=6),
            loc="upper right",
            bbox_to_anchor=(1.05, 1),
            title="Percent Passed",
        )

        if not self.title:
            self.title = "Window size analysis"
        plt.title(self.title)


class PlotTruncatedLCExperiment:
    def __init__(
        self,
        truncated_flares,
        categories=[
            "No Flare",
            "Flare",
            "Vary Flare Amplitude",
            "Vary Flare Rise Time",
        ],
        subcategories=["25", "50", "75", "100", "150", "200"],
        total_count=1300,
    ):
        self.truncated_flares = truncated_flares
        self.categories = categories
        self.subcategories = subcategories
        self.total_count = total_count

    def plot_truncated_lc_experiment(self):
        """
        do a comparison of heuristic performance giving varying window of data post GW, from 25-200 days post GW
        will heuristic work when we have limited post GW information
        """
        data = []

        for i in range(len(self.categories)):
            new_list = [category[i] for category in self.truncated_flares]
            data.append(new_list)

        colors = [
            (165 / 255, 42 / 255, 42 / 255, alpha)
            for alpha in np.linspace(0.1, 1.0, len(self.subcategories))
        ]

        # Plotting
        fig, ax = plt.subplots(figsize=(10, 6))
        width = 0.15  # bar width

        # Calculate percentages and plot bars for each subcategory within each category
        for i, cat_data in enumerate(data):
            for j, subcat_data in enumerate(cat_data):
                count = len(subcat_data)
                percentage = (count / self.total_count) * 100  # Calculate percentage
                # Position of the bar for this subcategory, within the group
                position = np.arange(len(self.categories)) + (j - 2) * width
                ax.bar(
                    position[i],
                    percentage,
                    width,
                    label=self.subcategories[j] if i == 0 else "",
                    color=colors[j],
                )

        ax.set_title("Real time heuristic performance")
        ax.set_xlabel("Set of Simulated AGN")
        ax.set_ylabel("Heuristic pass percentage (%)")
        ax.set_xticks(np.arange(len(self.categories)))
        ax.set_xticklabels(self.categories, rotation=20, ha="right")
        ax.legend(title="Days post GW")

        plt.tight_layout()
        plt.show()
