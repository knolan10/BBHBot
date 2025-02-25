from photometry_utils import PhotometryCoords, GetPhotometry, SavePhotometry

import argparse

parser = argparse.ArgumentParser(description='Get forced photometry from ZFPS.')
parser.add_argument('--verbose', action='store_false', help='Enable verbose output')
parser.add_argument('--action', type=str, required=True, help='Action to perform: all, new, update')
parser.add_argument('--graceid', type=str, required=True, help='Grace ID of the event')
parser.add_argument('--catalog', type=str, nargs='+', required=True, help='List of catalog names: quaia, catnorth')
parser.add_argument('--saving_photometry', type=bool, help='True will save completed ZFPS runs to the database')
parser.add_argument('--batch_codes', type=list, help='List of batch codes from completed ZFPS runs')
args = parser.parse_args()

if not args.saving_photometry:
    ra, dec, jd = PhotometryCoords(action=args.action, graceid=args.graceid, catalog=args.catalog, verbose=args.verbose).get_photometry_coords()
    GetPhotometry(graceid=args.graceid, ra=ra, dec=dec, jd=jd)

else:
    if args.batch_codes is None:
        parser.error("--batch_codes is required when action is 'save'")
    SavePhotometry(graceid=args.graceid, batch_codes=args.batch_codes, action=args.action).save_photometry()