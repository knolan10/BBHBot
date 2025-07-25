# Data

This directory contains data related to BBH followup and various logs related to BBHBot. Not all files here are pushed to github.


## events_summary

Summary of GW events, including information on how they were handled by BBHBot.

- error_trigger - any events with inconsitencies in trigger checking function including any missed triggers or unintended triggers
- trigger - all events that have been triggered on
- O4a - all O4a events
- O4a_priority - O4a events with mass > 60, a90 < 100, FAR > 10 years
- O4b - all O4b events
- O4b_priority - O4b events with mass > 60, a90 < 100, FAR > 10 years
- O4c - all O4c events
- O4c_priority - O4c events with mass > 60 or mchirp>22, a90 < 100, FAR > 10 years

## flare_data

Logs related to the EM counterpart search, including the final product of BBHBot: lists of flare candidates

### flares
Contains a file {Gracedbid}.json with the RA/dec coordinates of flaring candidates. There are coords lists for keys "flare_coords_g", "flare_coords_r", "flare_coords_i"

### dicts

Not tracked with git. The events_summary tables are nicely formatted versions of some of these data.

- crossmatch_dict_O4a.gz
- crossmatch_dict_O4b.gz
- crossmatch_dict_O4c.gz
- events_dict_O4a.json
- events_dict_O4b.json
- events_dict_O4c.json

### queued_for_photometry

Not tracked with git. Save files of coordinates here when we are at the limit of the ZFPS forced photometry service

### completed_queued_for_photometry

Not tracked with git. Move submitted files from queued_for_photometry here.

### ZFPS

Not tracked with git. ALL forced photometry lightcurves ever retrieved by BBHBot are saved here.

### photometry_pipeline.json

Keep track of all forced photometry requests made.

## logs

Printouts automatically saved by logger to files here.

## mchirp

Save chirp mass files retrieved from Gracedb

## trigger_data

Tracks all triggered events, and is used to record whether observations were successful and schedule the follow-up cadence of triggers.

- triggered_events.csv

## mlp_modle.sav

Outdated mass estimator, but still will be used to predict mass if chirp mass cannot be retrieved.
