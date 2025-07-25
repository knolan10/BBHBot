import argparse
import os


# TODO: add verbose argument here and/or in logging


def trigger_parser():
    parser = argparse.ArgumentParser(description="Listen to LIGO GCN and trigger ZTF")
    parser.add_argument(
        "--testing",
        action="store_true",
        help="Include --testing to run in testing mode, which prevents ZTF from being triggered among other things",
    )
    parser.add_argument(
        "--path_data",
        type=str,
        default="data",
        help="Path to data directory",
    )
    return parser


def trigger_parser_args():
    args = trigger_parser().parse_args()

    # validate the data directory path
    if not os.path.exists(args.path_data):
        raise ValueError(f"Invalid dataset path: {args.dataset_path}")
    return args


# TODO: here should i repeat code so i can have a unque parser for each script, bc in this case i want the same arguments


def followup_parser():
    parser = argparse.ArgumentParser(description="Listen to LIGO GCN and trigger ZTF")
    parser.add_argument(
        "--testing",
        action="store_true",
        help="Include --testing to run in testing mode, which prevents ZTF from being triggered among other things",
    )
    parser.add_argument(
        "--path_data",
        type=str,
        default="data",
        help="Path to data directory",
    )
    parser.add_argument(
        "--observing_run",
        type=str,
        default="O4c",
        choices=["O4a", "O4b", "O4c"],
        help="Current LIGO observing run",
    )
    return parser


def followup_parser_args():
    args = followup_parser().parse_args()

    # validate the data directory path
    if not os.path.exists(args.path_data):
        raise ValueError(f"Invalid dataset path: {args.dataset_path}")
    return args
