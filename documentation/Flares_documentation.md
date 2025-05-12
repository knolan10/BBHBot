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
2. Check how many coordinates we are currently waiting for photometry from. The ZFPS (Zwicky Transient Facility Forced Photometry) service limit is 15,000 coordinates pending at a given time.
3. Find any events that we need to request forced photometry for. For new events, we will get a two year baseline for all AGN that we do not have any locally saved photometry. We will also update the photometry to get the most recent data on a cadence of 9, 16, 23, 30, 52, 100 days post GW. This cadence roughly shadows the followup trigger cadence.
4. Find any events that have pending forced photometry requests, ie we have submitted the request and are waiting to save results. This can take hours to weeks depending on the request size and greater service usage.
5. If we ever hit the ZFPS request limit, we save all relevant info for any ZFPS requests that we should make to files in [queued_for_photometry](../data/flare_data/queued_for_photometry). We check this directory and submit as many queued requests as we can given the current number of requests pending.

### PART 1: Photometry Requests

Process all of the pending requests and requests to be submitted identified above.

1. Update records of all GW events. Instead of listening to the Kafka stream, we use the GraceDB API here. The current observing run (ie, 'O4c') must be set in the credentials file (which doubles as a place for "settings"). For any new significant BBH merger, including those that don't pass our trigger criteria, we will save that event to a table. We will also use Kowalski to do a crossmatch with the Catnorth AGN catalog. We automatically push updates to tables displaying event information, include which events have been triggered on, in the [events_summary](../data/events_summary) directory.

2. Find any new events that have BBHBot triggers. For these events, request 2 year baselines of forced photometry for all crossmatched AGN that we have no locally saved photometry for. We store all the forced photometry light curves as dataframes locally in the data directory, although we do not push these to github.

3. Add any events needing baseline forced photometry to all events in Part 0 which we have determined need updated photometry (ie get photometry up to the current time). We then submit these forced photometry requests and log them in [photometry_pipeline.json](../data/flare_data/photometry_pipeline.json) (described more below).

### PART 2: Retrieve Photometry

After the first update phometry request is made 9 days after the GW detection, each following day the script will check for the completed photometry. We also wait to save the baseline photometry request until 9 days in, as these tend to be larger requests (in terms of time coverage) that take longer to return, and we won't do any flare identification until we have post GW photometry anyways.

If part of a request (ie some but not all batches) return, we will wait to save the results until all the batches return.

Updated photometry is appended to the locally saved baselines for given AGN.

For any events that we successfully save photometry, we will save to a list to analyze in Part 3 below.

### PART 3: Flare identification

Take all events with updated photometry from part 2, and run heuristic for anomalous flares.

The heuristic uses statistics calculated on a rolling window. It calculates medians and median absolute deviations for 50 day windows over a 2 year baseline, and 25 day windows up to 200 days post gravitational wave detection. It saves the coordinates of lightcurves in g, r, and i for which the brightest median in the post GW windows is brighter than 3 times the median absolute deviation of 60% of baseline medians. This heuristic was determined with simulated data.

Every time this runs, we overwrite the flare results in the given event file in the directory [flares](../data/flare_data/flares/)

## More details

We use the [batched forced photometry service](https://web.ipac.caltech.edu/staff/fmasci/ztf/forcedphot.pdf) for ZTF maintained by IPAC.

For all photometry requests, if they will put us over the ZFPS photometry limit, we will save the submission information in a file in [queued_for_photometry](../data/flare_data/queued_for_photometry). We then move that file to [completed_queued_photometry](../data/flare_data/completed_queued_photometry) once the request has been successfully submitted.

We keep track of all photometry requests in the file [photometry_pipeline.json](../data/flare_data/photometry_pipeline.json). This is a dictionary with keys:

- "summary_stats" which tracks the total number of requests made, requests saved, and current number of pending requests. Due to some inconsistency in the ZFPS service, which may depend on latitude or something else, for most batched requests a couple percent of the submitted coordinates do not return results, so there are more requests made than requests saved.
- "events" which has an entry for every event in our ZFPS pipeline (every event triggered on). These in turn each have the key "zfps" which has a list of every ZFPS request made, and information including how many coordinates were in that request and whether they have been saved yet. We use this information to determine which events need updated photometry, and which requests we should check for results to save.

This script interacts with files and directories that we do not push to github, including the directory of saved ZFPS lightcurves within the data directory.
