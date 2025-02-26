# EM Follow-up

- [Introduction](#introduction)
- [In Depth Description](#in-depth-description)
- [Command Line](#command-line)
- [Credentials](#credentials)
- [Dependencies](#dependencies)


## Introduction
This is the code which automates the search for anomalous flares for merging binary black holes. The directory [flares](bot/data/flares) contains a lists of ra_dec for anomalous flares in g, r, and i bands for each event that has been processed.

Note - this code depends on various credentials and interacts with private local files.

## In Depth Description
This pipeline is broken into smaller steps in [emfollowup.ipynb](./emfollowup.ipynb) as an example.

The pipeline consists of [new_events.py](bot/new_events.py) &rarr; [photometry.py](bot/photometry.py) &rarr; [flares.py](bot/flares.py)

The full automated version runs in [main.py](bot/main.py)

### 1. [new_events.py](./new_events.py)

This script checks GraceDB for new superevents that have not been processed and saved locally. 

It gathers information on the new events such as the ZTF trigger status (and whether that matches the intended status), makes calculations such as an estimated total merger mass, and does AGN catalog crossmatches. 

It saves all of this information locally, and pushes to the directory [events_summary](../events_summary/).

### 2. [photometry.py](./photometry.py)

This script requests forced photometry for all the Catnorth AGN associated with a BBH merger from the Zwicky Transient Facility Forced Photometry Service. 

### 3. [flares.py](./flares.py)

This script uses rolling window statistics to filter for anomalous flares.

It calculates medians and median absolute deviations for 50 day windows over a 2 year baseline, and 25 day windows up to 200 days post gravitational wave detection. It saves the coordinates of lightcurves in g, r, and i for which the brightest median in the post GW windows is brighter than 3 times the median absolute deviation of 60% of baseline medians. This heuristic was determined with simulated data.


### The full version: [main.py](bot/main.py)

This script is designed to run once per day and handle two main tasks: (1) advancing events through the pipeline for anomalous flare detection and (2) ingesting any new mergers from gracedb.

First it checkes for pending tasks related to events actively being processed (ie in 200 day window post GW). 9 days after the gravitational wave detection (complementary to the followup ZTF trigger requested 7 days after the GW detection), this script with save the forced photometry requested for all AGN in the localization which have no existing photometry. It will then request an update to the photometry for all AGN in the localization.

The script will also request additional updates to photometry 20, 30, 50, and 100 after the GW detection. 

Once these updated phometry request are made, each following day the script will check for the completed photometry. Once it finds the completed photometry, it will run its rolling window heuristic for anomalous flares and save those results. Each time this runs on updated photometry, the results for anomalous flares will be overwritten.


## Credentials

### Required to Run
- **Fritz**: 
  - `fritz_token`
  - `allocation`

- **Kowalski**: 
  - `kowalski_password`

- **ZFPS (Forced Photometry Service)**: 
  - `zfps_email`
  - `zfps_userpass`
  - `zfps_auth`

- **Github**: 
  - `github_token`

## Dependencies

- `pandas`
- `numpy`
- `matplotlib`
- `scipy`
- `astropy`
- `requests`
- `xmltodict`
- `beautifulsoup4`
- `yaml`
- `ligo-gracedb`
- `penquins`

