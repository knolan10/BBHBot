# EM Follow-up

- [Introduction](#introduction)
- [In Depth Description](#in-depth-description)
- [Command Line](#command-line)
- [Credentials](#credentials)
- [Dependencies](#dependencies)


## Introduction
This is the code which automates the search for anomalous flares for merging binary black holes. The directory [flares](./flares.py) contains a lists of anomalous flares in g, r, and i bands for each event that has been processed.

Note - this code would need to be significantly modified for use, as it depends on various credentials and interacts with private local files that currently may not be easily replicable.

## In Depth Description
This pipeline is broken into smaller steps in [emfollowup.ipynb](./emfollowup.ipynb) as an example.

The pipeline consists of [new_events.py](./new_events.py) &rarr; [photometry.py](./photometry.py) &rarr; [flares.py](./flares.py)

### 1. [new_events.py](./new_events.py)

This script checks GraceDB for new superevents that have not been processed and saved locally. 

It gathers information on the new events such as the ZTF trigger status (and whether that matches the intended status), makes calculations such as an estimated total merger mass, and does AGN catalog crossmatches. 

It saves all of this information locally, and pushes to the public github repo [BBH](https://github.com/knolan10/BBH).

### 2. [photometry.py](./photometry.py)

### 3. [flares.py](./flares.py)

## Command Line


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

