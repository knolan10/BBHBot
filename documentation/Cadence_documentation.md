# Cadence

- [Overview](#Overview)
- [Step by step description](#Step-by-step-description)
- [More details](#More-details)

## Overview

This is the code which submits additional triggers to ensure optimal and standardized coverage of priority events over the 50 days post GW detection, and also handle resubmitting triggers in cases where we failed to observe.

## Step by step description

The steps executed in [cadence](../cadence.py) go as follows:

This script uses cron to run once per day at 1PM.

1. Find all pending triggers, whether they are from the initial trigger or a followup cadence trigger. Check whether we were successful in observing. If we were successful, we will update our logs. If we were not, we will automatically resubmit the trigger if it is within 2 days (otherwise, will need to be handled manually).

2. Find any events that need a followup trigger, ie for each event does todays date match any date in a list of dates generated with the cadence 7, 14, 21, 28, 40, and 50 days. Note - this is suceptible to missing followup triggers if the script doesn't run on a particular day, so should be closely monitored in its current version.

3. If we have found any unsucessful observations or prescheduled cadence observations to retrigger on, do so.

   - We use the same methods as in the initial trigger script. We request Fritz to generate an observing plan using Gwemopt. If the plan can cover probability > 0.5 in time < 5400 s, we add this plan to the ZTF queue.

   - If we submit to ZTF, we add the event to the "pending_observation" column of [triggered_events](../data/trigger_data/triggered_events.csv) and send an email notification.

## More details

- There is a "testing" bool set in the `trigger_credentials` file. If set to True, this will use the preview.fritz API, will prevent observation requests being actually sent to ZTF, and will not include all of the pauses built in designed to ensure smooth processing of real-time events.

- [triggered_events](../data/trigger_data/triggered_events.csv) is an important file that both the [trigger](../trigger.py) and [cadence](../cadence.py) scripts interact with. When a new event passes all criteria for a trigger, [trigger](../trigger.py) will add a new row for that event. Then, [cadence](../cadence.py) will edit that row as it checks whether triggers were successful and requests followup triggers. The columns in this file are:

  - superevent_id: the GraceDB assigned id
  - dateobs: the date of observation, which Fritz uses as an ID
  - gcn_type: preliminary, initial, update
  - gcn_id: Fritz assigned ID for the specific GCN
  - localization_id: Fritz assigned ID for the localization
  - trigger_cadence: the list of dates that followup triggers should happen on
  - pending_observation: recently submitted triggers that have not yet been confirmed as successful. Saved as (observation_plan_id, observation_plan_start_date)
  - unsuccessful_observation: unsuccessful pending moved to this column
  - successful_observation: successful pending moved to this column
  - serendipitous_observation: log any time we skip a trigger due to serendipitious coverage.
  - valid: True or False, set to False if event should not be considered anymore
