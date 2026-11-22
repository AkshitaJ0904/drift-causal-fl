# Probe Events in logs/finsentinel-siem.jsonl

## What happened

During the rule 100140 (brute-force correlation) investigation in the Phase 2 session
(2026-11-21), **13 events were written directly into `logs/finsentinel-siem.jsonl`**
by the agent rather than by the SIEM forwarder (`siem_forwarder.py`).

## Probe event client_ids and counts

| client_id | count | event_type |
|-----------|-------|------------|
| probe-brute-01 | 5 | security.signature_verification_failed |
| probe-100140-v2 | 5 | security.signature_verification_failed |
| alert-verify-1795198528 | 1 | security.signature_verification_failed |
| post-restart | 1 | security.signature_verification_failed |
| mapping-1795199009 | 1 | security.signature_verification_failed |
| **Total probes** | **13** | |

## Impact on counts

The **55 total `security.signature_verification_failed`** events in the JSONL file
include 13 probe events.  Rule 100104 alert count in OpenSearch reflects only
events that passed through the forwarder → manager → indexer pipeline; it does not
include probe events written directly to the JSONL file.

Rule 100140 was confirmed by the `bank-mumbai-54d76d` run (6 genuine events via the
forwarder).  The probe events also triggered additional 100140 alerts in the
indexer for the probe client_ids, but those are test artifacts.

## Status

Probe events are **not deleted** (the mandate prohibits destructive cleanup).
They are test records.  The JSONL file is append-only and meant to be written
only by `siem_forwarder.py` in normal operation.

## Table 1 correction

Rule 100104 count in Table 1 of Entry 75 (AGENTref.md) was listed as 11 for runs
fc7149+54d76d.  The 55 total in the full JSONL includes 13 probes + 42 real events
across 7 runs (fc7149, c43afb, 7b4e98, 3da0a7, 54d76d, and others).
