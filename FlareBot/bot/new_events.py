from new_events_utils import *
import argparse

parser = argparse.ArgumentParser(description='Process new events.')
parser.add_argument('--push', action='store_true', help='Enable push to public repository')
parser.add_argument('--verbose', action='store_false', help='Enable verbose output')
parser.add_argument('--check_before_run', action='store_true', help='At certain points require user input to continue')
args = parser.parse_args()

params = Gracedb().get_new_events()

eventid = [x[0] for x in params]
dateid = [x[12] for x in params]
a90 = [x[16] for x in params]
far = [x[9] for x in params]
mass = [x[22] for x in params]
trigger_status = Fritz(eventid, dateid, a90, far, mass).get_trigger_status()

df = NewEventsToDict(params, trigger_status, check_before_run=args.check_before_run).save_data()

skymap_str = [x[18] for x in params]
zmin = [x[19] for x in params]
zmax = [x[20] for x in params]
crossmatch = KowalskiCrossmatch(eventid, skymap_str, dateid, zmin, zmax)
new_events=crossmatch.check_events_to_crossmatch()
matches = crossmatch.get_crossmatches()

df, priority, trigger_df, error_triggers = PushEventsPublic(push=args.push, verbose=args.verbose).format_and_push()