# Trigger

- [Overview](#Overview)
- [Step by step description](#Step-by-step-description)
- [More details](#More-details)

## Overview
This is the code, running in realtime from December 2024 - present, which automatically triggers the Zwicky Transient Facility to observe the localizations of priority binary black hole merger gravitational wave detections.

## Step by step description
The steps executed in [trigger](../trigger.py) go as follows:

1. We begin consuming the GCN Kafka stream, listening for all LVC (LIGO) preliminary, initial, and update messages.

2. When we have a message, we extract event details. We look for events that are superevents, have not been retracted, are significant, are CBC events, have probability BBH > 0.5 and probability terrestrial < 0.4, have a false alarm rate > 10 (yr<sup>−1</sup>), and have a 90% probability area < 1000 (deg<sup>2</sup>).

    - If these criteria aren't met, we stop here. We check if a previous GCN from this event prompted a trigger, and if it did we edit our file tracking triggers to indicate that the event is no longer viable. We attempt to retract the submitted trigger if timing allows.
    - We skip over the first preliminary notice for events, because the second preliminary notice tends to come within seconds and have significantly improved inference. 

3. We then use our MLP model to predict the mass of the merger and select mergers with mass > 60 solar masses.
    - For merger mass < 60 solar masses, we stop here. Once again we check if a previous GCN for the event passed the mass cut, and if needed update the file tracking triggers to indicate that the event is no longer viable and attempt to retract any trigger.

4. We pause for 30 seconds to ensure the event has been loaded by Fritz. We then query Fritz every 30 seconds up to 5 minutes, until we can retrieve the GCN event from Fritz. We save the `gcnevent_id` and `localization_id` assigned by Fritz.

5. We submit a plan request to Fritz, which uses Gwemopt to produce an observing plan for ZTF and the given localization.

6. We pause for 15 seconds, and then begin querying Fritz every 30 seconds up to 5 minutes to retrieve the generated observing plan.

7. As an extra check, we retrieve the items in the ZTF queue for the upcoming night. We do a word search for the `superevent_id` from Gracedb, for the `dateobs` which is used as an identifier on Fritz, and for the `gcnevent_id` assigned by Fritz. If we find any of these ids, we note that there has been a trigger for this event. We check whether we triggered on the event, and if the trigger came from outside of BBHBot, we ultimately will not trigger.

8. We check if the observing plan has total_time < 5400 and probability > 0.5
    - If these criteria aren't met, we stop here, and indicate the event is no longer viable in our tracking file and retract any previous trigger if necessary.

9. If the event is more than a day old, we stop here.

10. If we have triggered on an earlier GCN for the event, we check if it is currently before sunset. If it is before sunset, we will remove our submitted trigger and submit a new trigger with the most recent inference.

11. We check coverage of the skymap over the previous two nights, and if we serendipitiously covered the 90% localization in that time period, then we will not trigger ZTF. However we will still create a log of this event along with all of the other triggered events, which will put it in the pipeline for automated followup observations and flare detection.

10. We submit the plan to the ZTF queue, and update our bookkeeping:
    - We add the event to [triggered_events](../data/trigger_data/triggered_events.csv)
    - We send an email notification of the trigger to a list of emails defined in the credentials file.

## More details
- We use a Docker container to run this program. A persistent volume is used to store a file that records our triggers in the [data](../data) directory.
- [mlp_model.sav](./mlp_model.sav) is trained on the known masses for LIGO O3 events using scikit-learn, and used to predict masses in real time in order to select high-mass mergers for follow-up.
- There is a "testing" bool set in the `trigger_credentials` file. If set to True, this will firstly control how we subscribe to the Kafka topics: it will generage a random configid, and only will listen for "update" GCN which is more time efficient for most testing needs. It will also use the preview.fritz API, will prevent observation requests being actually sent to ZTF, and will not include all of the pauses designed to ensure smooth processing of real-time events.