from photometry_utils import PhotometryCoords, GetPhotometry

import argparse

parser = argparse.ArgumentParser(description='Get forced photometry from ZFPS.')
parser.add_argument('--verbose', action='store_false', help='Enable verbose output')
parser.add_argument('--action', type=str, required=True, help='Action to perform: all, new, update')
parser.add_argument('--graceid', type=str, required=True, help='Grace ID of the event')
parser.add_argument('--catalog', type=str, nargs='+', required=True, help='List of catalog names: quaia, catnorth')
args = parser.parse_args()


ra, dec, jd = PhotometryCoords(action=args.action, graceid=args.graceid, catalog=args.catalog, verbose=args.verbose).get_photometry_coords()
GetPhotometry(graceid=args.graceid, ra=ra, dec=dec, jd=jd)