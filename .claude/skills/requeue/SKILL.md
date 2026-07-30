---
name: requeue
description: "Use when lessons have failed in the GK12 content pipeline and need another run, or when Shane says requeue, retry the pipeline, rerun failed lessons, or /requeue. Re-queues failed pipeline lessons and schedules a one-time Cloud Run retry."
---

# /requeue

Re-queues failed pipeline lessons and schedules a one-time Cloud Run retry.

## Usage

```
/requeue 2:00pm        # schedule retry at 2pm Central today
/requeue 4:30pm        # any time works
/requeue now           # trigger immediately, no scheduler job
```

## What you do

1. `git pull origin main` — get latest manifest from GitHub
2. `python scripts/pm_agent.py --retry-failed` — re-queue failed lessons
3. Commit + push the updated manifest to GitHub
4. If a time was given: create a one-time Cloud Scheduler job
   - Convert the time to UTC (Central = UTC-5 CDT / UTC-6 CST)
   - Job name: `gk12-retry-<MMDD>-<HHMM>` (e.g. `gk12-retry-0517-1400`)
   - Use `--time-zone="America/Chicago"` and cron `M H D Mo *`
   - If "now": run `gcloud run jobs execute gk12-lesson-pipeline --region us-central1 --project genesis-aios`
5. Confirm the `scheduleTime` in the response matches the intended time

## Auto-cleanup

`pm_agent.py` automatically deletes all `gk12-retry-*` scheduler jobs at the end of any non-8am run. No manual cleanup needed.

## Notes

- Missing-tab failures (currently C-088, M-035) will fail again until tabs are added to the Google Docs manually — this is expected and non-blocking
- The pipeline emails a summary to shane@gk12academy.com when the run completes
- Check logs: `gcloud run jobs executions list --job gk12-lesson-pipeline --region us-central1 --project genesis-aios`