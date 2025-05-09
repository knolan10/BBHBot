# EM Follow-up

- [Overview](#Overview)
- [Step by step description](#Step-by-step-description)
- [More details](#More-details)

## Overview
This is the code which automates the search for anomalous flares for merging binary black holes. The main steps are (1) maintaing updated forced photometry lightcurves for AGN crossmatched with the GW localization and (2) finding anomalous flares associated with the GW event using a rolling window heuristic. The directory [flares](../data/flares) contains files with lists of ra_dec coordinates for anomalous flares in g, r, and i bands for each event that has been processed. 

This pipeline is broken into smaller steps in [flares.ipynb](./flares.ipynb) as an example.

## Step by step description

The steps executed in [flares](../flares.py) go as follows:

This script uses cron to run once per day at 2PM.

### PART 0: Check status, try to submit queued requests

Do some forced photometry bookeeping. 

1. Check if any events are more than 200 days post GW, in which case we will update their status and stop checking them.
2. Check how many coordinates we are currently waiting for photometry from. The ZFPS service limit is 15,000 coordinates so we will not submit more than that number at once.
3. Find any events that we need to request forced photometry for. For new events, we will get a two year baseline for all AGN that we do not have any locally saved photometry. We will also update the photometry to get the most recent data on a cadence of 9, 16, 23, 30, 52, 100 days post GW. This cadence roughly follows the followup trigger cadence.
4. Find any events that have pending forced photometry requests, ie we have submitted the request and are waiting to save results. This can take hours to weeks depending on the request size and current service usage.
5. If we ever hit the ZFPS request limit, we save all relevant info for any ZFPS requests that we should make to files in [queued_for_photometry](../data/flare_data/queued_for_photometry). We check this directory and submit as many queued requests as we can given the current number of requests pending.

### PART 1: Photometry Requests

Process all of the pending requests and requests to be made identified above. 







First it checkes for pending tasks related to events actively being processed (ie in 200 day window post GW). 9 days after the gravitational wave detection (complementary to the followup ZTF trigger requested 7 days after the GW detection), this script will save the forced photometry requested for all AGN in the localization which have no existing photometry. It will then request an update to the photometry for all AGN in the localization.

The script will also request additional updates to photometry 20, 30, 50, and 100 after the GW detection. 

Once these updated phometry request are made, each following day the script will check for the completed photometry. Once it finds the completed photometry, it will run its rolling window heuristic for anomalous flares and save those results. Each time this runs on updated photometry, the results for anomalous flares will be overwritten.

This script checks GraceDB for new superevents that have not been processed and saved locally. 

It gathers information on the new events such as the ZTF trigger status (and whether that matches the intended status), makes calculations such as an estimated total merger mass, and does AGN catalog crossmatches. 

It saves all of this information locally, and pushes to the directory [events_summary](../events_summary/).


This script requests forced photometry for all the Catnorth AGN associated with a BBH merger from the Zwicky Transient Facility Forced Photometry Service. 

This script uses rolling window statistics to filter for anomalous flares.

It calculates medians and median absolute deviations for 50 day windows over a 2 year baseline, and 25 day windows up to 200 days post gravitational wave detection. It saves the coordinates of lightcurves in g, r, and i for which the brightest median in the post GW windows is brighter than 3 times the median absolute deviation of 60% of baseline medians. This heuristic was determined with simulated data.



## More details

We use the [batched forced photometry service](https://web.ipac.caltech.edu/staff/fmasci/ztf/forcedphot.pdf) for ZTF maintained by IPAC.

This script depends on some local files and "path_data" set in the credentials file.
