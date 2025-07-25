# BBHBot

Automated follow-up for the optical flares of binary black hole mergers

Run trigger to listen to LIGO BBH detections in real time and trigger ZTF on priority events:

```bash
PYTHONPATH=. python trigger
```

Run cadence daily to get subsequent ZTF triggers over 50 days post GW detection, ensuring good coverage of priority events.

```bash
PYTHONPATH=. python cadence
```

Run flares daily to log all LIGO events, get ZTF forced photometry lightcurves for all AGN spatially coincident with priority GW localizations, and filter for anomalous flares that are candidate EM counterparts.

```bash
PYTHONPATH=. python flares
```
