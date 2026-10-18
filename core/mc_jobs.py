"""
mc_jobs.py — In-memory registry of long operations started through the API.

A job runs a function in its own thread. It is queued, then running, then
succeeded, failed or cancelled; finished jobs are purged after an hour.
"""
import datetime
import logging
import threading
import time
import uuid

import mc_api

RETENTION_S = 3600
STATES = ("queued", "running", "succeeded", "failed", "cancelled")
FINISHED = ("succeeded", "failed", "cancelled")


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Job:
    def __init__(self, kind, server, created):
        self.id = "j_" + uuid.uuid4().hex[:12]
        self.kind = kind
        self.server = server
        self.state = "queued"
        self.progress = None
        self.result = None
        self.created = created
        self.updated = created
        self.finished = threading.Event()

    def document(self):
        code = self.result.get("code") if self.result else None
        return {"id": self.id, "kind": self.kind, "server": self.server, "state": self.state,
                "progress": self.progress, "code": code, "result": self.result,
                "created_at": _iso(self.created), "updated_at": _iso(self.updated)}


class Registry:
    def __init__(self, on_change=None, clock=time.time, retention=RETENTION_S):
        self.on_change = on_change
        self.clock = clock
        self.retention = retention
        self.jobs = {}
        self.lock = threading.Lock()

    def _changed(self, job):
        if self.on_change:
            try:
                self.on_change(job.document())
            except Exception:
                logging.exception("job listener failed")

    def submit(self, kind, server, function, settle=0.0):
        """Start `function(progress)` in a thread; returns the job. With `settle`,
        waits that long for a quick outcome."""
        self.purge()
        job = Job(kind, server, self.clock())
        with self.lock:
            self.jobs[job.id] = job
        self._changed(job)
        threading.Thread(target=self._run, args=(job, function), daemon=True, name="job-" + job.id).start()
        if settle:
            job.finished.wait(settle)
        return job

    def _progress(self, job):
        def report(done, total=None):
            if job.state not in ("queued", "running"):
                return
            if total:
                job.progress = max(0, min(99, int(done * 100 / total)))
            elif isinstance(done, (int, float)):
                job.progress = max(0, min(99, int(done)))
            else:
                return
            job.updated = self.clock()
            self._changed(job)
        return report

    def _run(self, job, function):
        job.state = "running"
        job.progress = 0
        job.updated = self.clock()
        self._changed(job)
        try:
            outcome = function(self._progress(job))
            if not isinstance(outcome, dict):
                outcome = mc_api.result(True, "done")
        except Exception as exc:
            logging.exception("job %s failed", job.kind)
            outcome = mc_api.result(False, "internal_error", detail=type(exc).__name__)
        if job.state == "cancelled":
            job.finished.set()
            return
        job.result = mc_api.wire(outcome)
        job.state = "succeeded" if outcome.get("ok") else "failed"
        if outcome.get("ok"):
            job.progress = 100
        job.updated = self.clock()
        job.finished.set()
        self._changed(job)

    def get(self, job_id):
        return self.jobs.get(job_id)

    def listing(self, state=None):
        self.purge()
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created)
        return [j.document() for j in jobs if state in (None, j.state)]

    def cancel(self, job_id):
        """True when cancelled, False when already finished, None when unknown."""
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if job.state in FINISHED:
            return False
        job.state = "cancelled"
        job.updated = self.clock()
        job.finished.set()
        self._changed(job)
        return True

    def discard(self, job_id):
        with self.lock:
            self.jobs.pop(job_id, None)

    def purge(self):
        limit = self.clock() - self.retention
        with self.lock:
            for job_id in [i for i, j in self.jobs.items() if j.state in FINISHED and j.updated < limit]:
                del self.jobs[job_id]
