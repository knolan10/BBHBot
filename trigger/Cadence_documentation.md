# Cadence

- [Introduction](#introduction)
- [In Depth Description](#in-depth-description)
- [Technical Points](#technical-points)
- [Credentials](#credentials)

## Introduction
This is the code, currently being tested, to handle the followup of the intitial ZTF trigger descriped in [Trigger_documentation](./Trigger_documentation.md). This includes excution of additional triggers over the following 50 days, and retriggering in cases where we failed to observe.

## In Depth Description
The steps executed in [cadence](./cadence.py) go as follows:

## Technical Points
- There is a "testing" bool set in the `trigger_credentials.yaml` file. If set to True, this will use the preview.fritz API, will prevent observation requests being actually sent to ZTF, and will not include all of the pauses built in designed to ensure smooth processing of real-time events.

## Credentials

### Required to Run
- **Fritz**: 
  - `fritz_token`
- **Email Notice of Triggers**: 
  - `sender_email`
  - `sender_password`
  - `recipient_emails`

### Testing Mode
- `preview_fritz_token`