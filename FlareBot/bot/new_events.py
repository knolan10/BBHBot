from new_events_utils import *
import argparse

parser = argparse.ArgumentParser(description='Process new events.')
parser.add_argument('--push', action='store_true', help='Enable push to public repository')
parser.add_argument('--verbose', action='store_false', help='Enable verbose output')
parser.add_argument('--check_before_run', action='store_true', help='At certain points require user input to continue')
parser.add_argument('--path_events_dictionary', default='data/', help='Path to the events dictionary')
parser.add_argument('--mlp_modelpath', default='mlp_model.sav', help='Path to the MLP model')
parser.add_argument('--event_source', type=str, help='Options: gracedb, kafka')

args = parser.parse_args()

params = GetSuperevents(path_events_dictionary=args.path_events_dictionary, 
                 mlp_modelpath=args.mlp_modelpath,
                 event_sorce=args.event_source).get_new_events()

eventid = [x[0] for x in params]
dateid = [x[12] for x in params]
a90 = [x[16] for x in params]
far = [x[9] for x in params]
mass = [x[22] for x in params]
trigger_status = Fritz(eventid, dateid, a90, far, mass).get_trigger_status()

df = NewEventsToDict(params, trigger_status, args.path_events_dictionary, check_before_run=args.check_before_run).save_data()

skymap_str = [x[18] for x in params]
zmin = [x[19] for x in params]
zmax = [x[20] for x in params]
crossmatch = KowalskiCrossmatch(eventid, skymap_str, dateid, zmin, zmax, args.path_events_dictionary)
new_events=crossmatch.check_events_to_crossmatch()
matches = crossmatch.get_crossmatches()

df, priority, trigger_df, error_triggers = PushEventsPublic(args.path_events_dictionary,
                                                            push=args.push, 
                                                            verbose=args.verbose).format_and_push()
