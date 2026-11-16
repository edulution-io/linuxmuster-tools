"""
History of the linbo-remote runs, read from the run record linuxmuster-linbo7
appends to ``<LINBO_LOG_PATH>/linbo-remote_runs.jsonl``: one JSON line per
host and run, with ``v``, ``run_id`` (shared by all hosts of one invocation),
``user``, ``hostname``, ``mode``, ``commands``, ``dry_run``, ``start``,
``log``, ``end`` and ``rc``.

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


def _start_key(run):
    """
    Sort key of a run by its start time. Records written by older linbo-remote
    versions use a +0200 offset, newer ones +02:00; both parse. Without a
    readable start a run sorts last.
    """

    try:
        return datetime.fromisoformat(run['start']).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


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
    def _host(record):
        rc = record.get('rc')
        return {
            'hostname': record['hostname'],
            'start': record.get('start'),
            'end': record.get('end'),
            'rc': rc,
            'status': 'running' if rc is None else ('ok' if rc == 0 else 'failed'),
            'log': os.path.basename(record['log']) if record.get('log') else None,
        }

    def _runs(self, hostnames):
        runs = {}
        for record in self._records():
            if hostnames is not None and record['hostname'] not in hostnames:
                continue
            run_id = self._run_id(record)
            host = self._host(record)
            run = runs.setdefault(run_id, {
                'runId': run_id,
                'user': record.get('user'),
                'commands': record.get('commands', []),
                'dryRun': bool(record.get('dry_run', False)),
                'mode': record.get('mode'),
                'start': host['start'],
                'end': host['end'],
                'hosts': [],
            })
            run['hosts'].append(host)
            run['start'] = min(filter(None, [run['start'], host['start']]), default=None)
            ends = [h['end'] for h in run['hosts']]
            run['end'] = None if None in ends else max(ends)

        for run in runs.values():
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
