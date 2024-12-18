# Trigger

## Table of Contents
- [Introduction](#introduction)
- [In Depth Description](#in-depth-description)
- [Phase 2 Additions](#phase-2-additions)
- [Technical Points](#technical-points)
- [Credentials](#credentials)

## Introduction
This is the code, running in realtime from December 2024 - present, which automatically triggers the Zwicky Transient Facility to observe the localizations of priority binary black merger gravitational wave detections.

## In Depth Description
The steps executed in [main](./main.py) go as follows:

1. We begin consuming the GCN Kafka stream, listening for all LVC (LIGO) messages.

2. When we have a message, we extract event details. We look for events that are superevents, have not been retracted, are significant, are CBC events, have probability BBH > 0.5 and probability terrestrial < 0.4, have a false alarm rate > 10, and have a 90% probability area > 1000 square degrees.
    - If these criteria aren't met, we stop here. We check if a previous GCN from this event prompted a trigger, and if it did we edit our file tracking triggers to indicate that the event is no longer viable.
    - We skip over the first preliminary notice for events, because the second preliminary notice tends to come within seconds and have significantly improved inference. Events notices are classified as preliminary, initial, and update.

3. We then use our MLP model to predict the mass of the merger and select mergers with mass > 60 solar masses.
    - For merger mass < 60 solar masses, we stop here. Once again we check if a previous GCN for the event passed the mass cut, and if needed update the file tracking triggers to indicate that the event is no longer viable.

4. We pause for 30 seconds to ensure the event has been loaded by Fritz. We then query Fritz every 30 seconds up to 5 minutes, until we can retrieve the GCN event from Fritz. We save the `gcnevent_id` and `localization_id` assigned by Fritz.

5. We submit a plan request to Fritz, which uses Gwemopt to produce an observing plan for ZTF and the given localization.

6. We then pause for 15 seconds, and then begin querying Fritz every 30 seconds up to 5 minutes to retrieve the generated observing plan.

7. As an extra check, we retrieve the items in the ZTF queue for the upcoming night. We do a wordsearch for the superevent id from Gracedb, for the date observed which is used as an identifier on Fritz, and for the `gcnevent_id` assigned by Fritz. If we find any of these ids, we note that there has been a trigger by another group, and while we continue some more steps, we ultimately will not trigger.

8. We check if the plan has total_time < 5400 and probability > 0.5
    - If these criteria aren't met, we stop here, and indicate the event is no longer viable in our tracking file if necessary.

9. Now we are left with good events for a trigger. However, we or another group may have already triggered on the event! We process already triggered events up to this point so that if they were submitted but the latest GCN make them no longer viable, then we can record that.
    - If the event has been triggered by us, or was found in the ZTF queue for this night, we stop here.

10. We submit the plan to the ZTF queue, and update our bookkeeping:
    - We add the event to [triggered_events](./data/triggered_events.csv)
    - We send an email notification of the trigger

## Phase 2 Additions 

1. A separate script will regularly check the [triggered_events](./data/triggered_events.csv) and submit additional observations for triggered events over a period of 50 days.

2. If it is before the start of the night and we receive a new GCN for a triggered event, we retract the submitted trigger and submit the new plan.

3. Check for ZTF observations the previous 2 nights and skip TOO if the localization was already covered.

## Technical Points
- We use a Docker container to run this program. A persistent volume is used to store a file that records our triggers in the [data](./data) directory.
- [mlp_model.sav](./mlp_model.sav) is trained on the known masses for LIGO O3 events, and used to predict masses in real time in order to select high-mass mergers for follow-up.
- There is a "testing" bool set in the `trigger_credentials.yaml` file. If set to True, this will use the preview.fritz API, will prevent observation requests being actually sent to ZTF, and will not include all of the pauses built in designed to ensure smooth processing of real-time events.

## Credentials

### Required to Run
- **Fritz**: 
  - `fritz_token`
  - `allocation`
- **GCN Kafka**: 
  - `client_id`
  - `client_secret`
- **Email Notice of Triggers**: 
  - `sender_email`
  - `sender_password`
  - `recipient_emails`

### Testing Mode
- `preview_fritz_token`
- `preview_allocation`