"""
History of the linbo-remote runs, read from the run record linuxmuster-linbo7
appends to ``<LINBO_LOG_PATH>/linbo-remote_runs.jsonl``. Each line belongs to
one host and run and carries ``v``, ``run_id`` (shared by all hosts of one
invocation), ``user``, ``hostname``, ``mode``, ``commands``, ``dry_run``,
``start`` and ``log``.

Since record version 2, linbo-remote writes two lines per host: a start line
when the host's run begins, without ``end`` and ``rc``, and an end line with
both when it exits. A host with only its start line is reported as
``running``, and its log can be read while it grows. Version 1 wrote the end
line only, so those runs show their finished hosts. A start line whose end
line never comes (the server went down, the script was killed with SIGKILL)
stays ``running``.

``rc`` is the exit status of the remote script. For a backgrounded start,
reboot, halt or poweroff, ``0`` only means that the command was dispatched.
A run killed by a signal is recorded with 128 plus the signal number.
"""

import json
import logging
import os
from datetime import datetime, timezone

from . import config as config_module
from .boot_logs import LinboBootLogs
from ..devices import Devices

RUN_RECORD_FILE = 'linbo-remote_runs.jsonl'
DEFAULT_LIMIT = 50
logger = logging.getLogger(__name__)


def _instant(value):
    """
    A timestamp of the run record as an aware datetime, None if it is missing
    or unreadable. Records written by older linbo-remote versions use a +0200
    offset, newer ones +02:00; both parse. Compare these, never the strings:
    different offsets (DST) order wrongly as text.
    """

    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _start_key(run):
    """Sort key of a run by its start time; without a readable start a run sorts last."""

    return _instant(run['start']) or datetime.min.replace(tzinfo=timezone.utc)


def _earliest(values):
    """The earliest of the timestamps by instant, unreadable ones only if none is readable."""

    values = [v for v in values if v]
    return min(values, key=lambda v: (_instant(v) is None, _instant(v) or 0), default=None)


def _latest(values):
    """The latest of the timestamps by instant, unreadable ones only if none is readable."""

    values = [v for v in values if v]
    readable = [v for v in values if _instant(v)]
    return max(readable or values, key=lambda v: _instant(v) or 0, default=None)


class LinboRunNotFoundError(LookupError):
    """Raised when a run, or a host's log of it, does not exist."""


def school_hostnames(school):
    """
    The host names of a school as they appear in the run record: the plain
    name for default-school, ``<school>-<name>`` for every other school.

    :param school: School name
    :return: Set of host names
    """

    prefix = '' if school == 'default-school' else f'{school}-'
    return {f'{prefix}{device["hostname"]}' for device in Devices(school=school).devices if device['hostname']}


class LinboRunReader:
    """
    Read the linbo-remote run record. All methods take an optional set of
    host names: only those hosts are reported, and a run without any of them
    is left out, so a school-administrator sees the runs of their own school.
    """

    def __init__(self, log_dir=None):
        self.log_dir = log_dir or config_module.LINBO_LOG_PATH

    def _records(self):
        path = os.path.join(self.log_dir, RUN_RECORD_FILE)
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
        except OSError:
            return []

        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                logger.warning(f'Skipping an unreadable line of {path}')
                continue
            if isinstance(record, dict) and isinstance(record.get('hostname'), str) and record['hostname']:
                records.append(record)
        return records

    @staticmethod
    def _run_id(record):
        # Records written before run ids existed are a run of one host each.
        return record.get('run_id') or f'{record.get("start", "")}_{record["hostname"]}'

    @staticmethod
    def _is_end_line(record):
        # The start line of a host has no rc; its end line always has one.
        return 'rc' in record

    @classmethod
    def _host(cls, record):
        rc = record.get('rc')
        if not cls._is_end_line(record):
            status = 'running'
        else:
            status = 'ok' if rc == 0 else 'failed'
        return {
            'hostname': record['hostname'],
            'start': record.get('start'),
            'end': record.get('end'),
            'rc': rc,
            'status': status,
            'log': os.path.basename(record['log']) if record.get('log') else None,
        }

    def _runs(self, hostnames):
        runs = {}
        for record in self._records():
            if hostnames is not None and record['hostname'] not in hostnames:
                continue
            run_id = self._run_id(record)
            run = runs.setdefault(run_id, {
                'runId': run_id,
                'user': record.get('user'),
                'commands': record.get('commands', []),
                'dryRun': bool(record.get('dry_run', False)),
                'mode': record.get('mode'),
                'hosts': {},
            })
            hosts = run['hosts']
            known = hosts.get(record['hostname'])
            # A host's end line replaces its start line, and a late start line
            # never hides the end line already read.
            if known is None or self._is_end_line(record) or known['status'] == 'running':
                hosts[record['hostname']] = self._host(record)

        for run in runs.values():
            run['hosts'] = list(run['hosts'].values())
            run['start'] = _earliest([h['start'] for h in run['hosts']])
            ends = [h['end'] for h in run['hosts']]
            run['end'] = None if None in ends else _latest(ends)
            statuses = {h['status'] for h in run['hosts']}
            run['status'] = 'running' if 'running' in statuses else ('failed' if 'failed' in statuses else 'ok')
        return runs

    def list_runs(self, hostnames=None, limit=DEFAULT_LIMIT):
        """
        :param hostnames: Only report these hosts, None for all
        :param limit: Number of runs, newest first
        :return: List of run dicts without their host logs
        """

        runs = sorted(self._runs(hostnames).values(), key=_start_key, reverse=True)
        return runs[:limit]

    def get_run(self, run_id, hostnames=None):
        """
        :raises LinboRunNotFoundError: no such run, or none of its hosts is in hostnames
        """

        run = self._runs(hostnames).get(run_id)
        if run is None:
            raise LinboRunNotFoundError(f'Run {run_id} not found.')
        return run

    def read_run_log(self, run_id, hostname, hostnames=None):
        """
        The log of one host in one run.

        :raises LinboRunNotFoundError: no such run or host in it, or its log is gone
        :raises ValueError: the recorded log name is not a plain file name
        """

        run = self.get_run(run_id, hostnames)
        for host in run['hosts']:
            if host['hostname'] == hostname and host['log']:
                content = LinboBootLogs(self.log_dir).read_log(host['log'])
                if content is None:
                    raise LinboRunNotFoundError(f'The log of {hostname} in run {run_id} is gone.')
                return content
        raise LinboRunNotFoundError(f'Host {hostname} not in run {run_id}.')
