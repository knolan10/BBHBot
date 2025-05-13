from flares_utils import FlarePreprocessing, RollingWindowStats, RollingWindowHeuristic

import argparse

parser = argparse.ArgumentParser(description="Get forced photometry from ZFPS.")
parser.add_argument("--verbose", action="store_false", help="Enable verbose output")
parser.add_argument("--graceid", type=str, required=True, help="Grace ID of the event")
parser.add_argument(
    "--heuristic_mad_scalar",
    type=float,
    required=False,
    help="the scalar on the mean absolute deviations that a point in the GW window must be brighter than",
)
parser.add_argument(
    "--heuristic_percent",
    type=float,
    required=False,
    help="percent defines the percentage of baseline medians that must meet this criteria",
)
parser.add_argument(
    "--save", action="store_true", help="Save the the results of the flare locally"
)
parser.add_argument(
    "--path_events_dictionary", default="data/", help="Path to the events dictionary"
)
parser.add_argument(
    "--path_photometry", default="mlp_model.sav", help="Path to the MLP model"
)
args = parser.parse_args()


AGN = FlarePreprocessing(
    graceid=args.graceid,
    path_events_dictionary=args.path_events_dictionary,
    path_photometry=args.path_photometry,
).process_for_flare()

stats = RollingWindowStats(
    graceid=args.graceid, agn=AGN, path_events_dictionary=args.path_events_dictionary
).get_rolling_window_stats()

g, r, i = RollingWindowHeuristic(
    graceid=args.graceid,
    agn=AGN,
    rolling_stats=stats,
    path_events_dictionary=args.path_events_dictionary,
    percent=args.heuristic_percent,
    k_mad=args.heuristic_mad_scalar,
    save=args.save,
).get_flares()
