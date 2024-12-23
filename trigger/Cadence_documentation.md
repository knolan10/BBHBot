# Cadence

- [Introduction](#introduction)
- [In Depth Description](#in-depth-description)
- [Technical Points](#technical-points)
- [Credentials](#credentials)

## Introduction
This is the code, currently being tested, to handle the followup of the intitial ZTF trigger descriped in [Trigger_documentation](./Trigger_documentation.md). This includes excution of additional triggers over the following 50 days, and retriggering in cases where we failed to observe.

## In Depth Description
The steps executed in [cadence](./cadence.py) go as follows:

Rather than running continuously, this script is automated to run once per day at 12PM.

1. Check if we submitting anything for obervation the previous night.

- When we submit an automated request for observation (an initial TOO for a new event or a subsequent TOO for an event we have triggered), we add that event to the "pending" column of [triggered_events.csv](./data/triggered_events.csv), so we just check if there are any events there.

- For each pending observation, we check whether there were successful observations the previous night. If there were, we move the event into the "successful_observation" column. If there weren't but the event is fewer than two days old, we will request a plan for the upcoming night. If there weren't and the event is older than two days, we send an email notification and move the event into the "unsuccessful_observation" column.

- We then check the "trigger_cadence" column entries, which are lists of dates 7, 14, 21, 28, 40, and 50 days after the gravitational wave detections. If the current date matches any of these dates, then we will request a plan for the upcoming night.

2. If we have found any unsucessful observations or prescheduled cadence observations to request an observing plan for, we do so here.

- We use the same methods as in the initial trigger script. We request Fritz to generate an observing plan using Gwemopt. If the plan can cover probability > 0.5 in time < 5400 s, we add this plan to the ZTF queue.

- If we submit for observation, we add the event to the "pending" column if necessary and send an email notification.

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