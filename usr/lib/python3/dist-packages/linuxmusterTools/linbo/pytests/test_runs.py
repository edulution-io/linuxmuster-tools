"""
Tests for the linbo-remote run history (LinboRunReader) and the --run-user
option of LinboRemote.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import linuxmusterTools.linbo.runs as runs_module
import linuxmusterTools.linbo.linbo_sync as linbo_sync_module
from linuxmusterTools.linbo.linbo_sync import LinboRemote, LinboRemoteParameterError, supports_run_user
from linuxmusterTools.linbo.runs import LinboRunNotFoundError, LinboRunReader, school_hostnames


def record(hostname, run_id='20261001120000-100', rc=0, start='2026-10-01T12:00:00+02:00',
           end='2026-10-01T12:05:00+02:00', user='alice', commands=('sync:1',), log=None, **extra):
    data = {
        'v': 1, 'run_id': run_id, 'user': user, 'hostname': hostname, 'mode': 'direct',
        'commands': list(commands), 'dry_run': False, 'start': start,
        'log': log or f'/var/log/linuxmuster/linbo/{hostname}_linbo-remote_20261001120000.log',
    }
    if end is not None:
        data['end'] = end
    if rc is not None:
        data['rc'] = rc
    data.update(extra)
    return json.dumps(data)


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / 'var_log_linbo'


def write_records(log_dir, *lines):
    (log_dir / 'linbo-remote_runs.jsonl').write_text('\n'.join(lines) + '\n')


# ── list_runs / get_run ──────────────────────────────────────────────────


def test_no_record_file_means_no_runs(log_dir):
    assert LinboRunReader().list_runs() == []


def test_hosts_of_one_invocation_form_one_run(log_dir):
    write_records(log_dir, record('r1-pc01'), record('r1-pc02', rc=1))
    runs = LinboRunReader().list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run['runId'] == '20261001120000-100'
    assert run['user'] == 'alice'
    assert run['commands'] == ['sync:1']
    assert [h['hostname'] for h in run['hosts']] == ['r1-pc01', 'r1-pc02']
    assert [h['status'] for h in run['hosts']] == ['ok', 'failed']
    assert run['status'] == 'failed'


def test_runs_are_listed_newest_first_and_limited(log_dir):
    write_records(
        log_dir,
        record('pc01', run_id='a', start='2026-10-01T10:00:00+02:00'),
        record('pc01', run_id='c', start='2026-10-03T10:00:00+02:00'),
        record('pc01', run_id='b', start='2026-10-02T10:00:00+02:00'),
    )
    reader = LinboRunReader()
    assert [r['runId'] for r in reader.list_runs()] == ['c', 'b', 'a']
    assert [r['runId'] for r in reader.list_runs(limit=2)] == ['c', 'b']


def test_a_host_without_end_and_rc_is_still_running(log_dir):
    write_records(log_dir, record('pc01', rc=None, end=None), record('pc02'))
    run = LinboRunReader().list_runs()[0]
    assert [h['status'] for h in run['hosts']] == ['running', 'ok']
    assert run['status'] == 'running'
    assert run['end'] is None


def test_run_start_and_end_span_all_hosts(log_dir):
    write_records(
        log_dir,
        record('pc01', start='2026-10-01T12:00:05+02:00', end='2026-10-01T12:04:00+02:00'),
        record('pc02', start='2026-10-01T12:00:01+02:00', end='2026-10-01T12:09:00+02:00'),
    )
    run = LinboRunReader().list_runs()[0]
    assert run['start'] == '2026-10-01T12:00:01+02:00'
    assert run['end'] == '2026-10-01T12:09:00+02:00'


def test_records_without_run_id_are_runs_of_their_own(log_dir):
    old = json.loads(record('pc01'))
    del old['run_id'], old['user'], old['v']
    write_records(log_dir, json.dumps(old), record('pc02', run_id=None, user=None))
    runs = LinboRunReader().list_runs()
    assert len(runs) == 2
    assert {r['hosts'][0]['hostname'] for r in runs} == {'pc01', 'pc02'}
    assert all(r['user'] is None for r in runs)


def test_unreadable_lines_are_skipped(log_dir):
    write_records(log_dir, 'not json', '[1, 2]', record('pc01'), '{"no": "hostname"}', '')
    assert [r['hosts'][0]['hostname'] for r in LinboRunReader().list_runs()] == ['pc01']


def test_hostnames_filter_hosts_and_drops_empty_runs(log_dir):
    write_records(
        log_dir,
        record('abc-pc01', run_id='mine'), record('xyz-pc01', run_id='mine'),
        record('xyz-pc02', run_id='theirs'),
    )
    reader = LinboRunReader()
    runs = reader.list_runs(hostnames={'abc-pc01', 'abc-pc02'})
    assert [r['runId'] for r in runs] == ['mine']
    assert [h['hostname'] for h in runs[0]['hosts']] == ['abc-pc01']
    with pytest.raises(LinboRunNotFoundError):
        reader.get_run('theirs', hostnames={'abc-pc01'})


def test_get_run_returns_the_run(log_dir):
    write_records(log_dir, record('pc01', run_id='a'), record('pc01', run_id='b'))
    assert LinboRunReader().get_run('b')['runId'] == 'b'
    with pytest.raises(LinboRunNotFoundError):
        LinboRunReader().get_run('nope')


# ── read_run_log ─────────────────────────────────────────────────────────


def test_read_run_log_returns_the_log_of_the_host(log_dir):
    name = 'pc01_linbo-remote_20261001120000.log'
    (log_dir / name).write_text('synced\n')
    write_records(log_dir, record('pc01', log=f'/var/log/linuxmuster/linbo/{name}'))
    assert LinboRunReader().read_run_log('20261001120000-100', 'pc01') == 'synced\n'


def test_read_run_log_of_a_deleted_log_is_not_found(log_dir):
    write_records(log_dir, record('pc01'))
    with pytest.raises(LinboRunNotFoundError):
        LinboRunReader().read_run_log('20261001120000-100', 'pc01')


def test_read_run_log_of_a_host_not_in_the_run_is_not_found(log_dir):
    write_records(log_dir, record('pc01'))
    with pytest.raises(LinboRunNotFoundError):
        LinboRunReader().read_run_log('20261001120000-100', 'pc99')


def test_read_run_log_of_a_foreign_host_is_not_found(log_dir):
    name = 'xyz-pc01_linbo-remote_20261001120000.log'
    (log_dir / name).write_text('secret\n')
    write_records(log_dir, record('xyz-pc01', log=f'/var/log/linuxmuster/linbo/{name}'))
    with pytest.raises(LinboRunNotFoundError):
        LinboRunReader().read_run_log('20261001120000-100', 'xyz-pc01', hostnames={'abc-pc01'})


def test_read_run_log_never_leaves_the_log_dir(log_dir, tmp_path):
    (tmp_path / 'secret.log').write_text('secret\n')
    write_records(log_dir, record('pc01', log='/var/log/linuxmuster/linbo/../../../secret.log'))
    # only the base name of the recorded path is used
    with pytest.raises(LinboRunNotFoundError):
        LinboRunReader().read_run_log('20261001120000-100', 'pc01')


# ── school_hostnames ─────────────────────────────────────────────────────


def test_school_hostnames_prefix_non_default_schools(monkeypatch):
    devices = [{'hostname': 'pc01'}, {'hostname': 'pc02'}, {'hostname': ''}]
    monkeypatch.setattr(runs_module, 'Devices', lambda school: MagicMock(devices=devices))
    assert school_hostnames('default-school') == {'pc01', 'pc02'}
    assert school_hostnames('abc') == {'abc-pc01', 'abc-pc02'}


# ── --run-user ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_run_user_probe():
    linbo_sync_module._run_user_support.clear()
    yield
    linbo_sync_module._run_user_support.clear()


def help_output(text):
    return patch('linuxmusterTools.linbo.linbo_sync.subprocess.run', return_value=MagicMock(stdout=text))


def test_run_user_is_passed_when_linbo_remote_knows_the_option():
    with help_output(' --run-user <name>  Name recorded as the starter\n'):
        remote = LinboRemote(clients=['10.0.0.5'], cmd='reboot', run_user='alice')
        remote.build()
    assert remote.built_cmd.endswith(' --run-user alice -c reboot')


def test_run_user_is_left_out_for_an_older_linbo_remote():
    with help_output(' -h  Show this help.\n'):
        remote = LinboRemote(clients=['10.0.0.5'], cmd='reboot', run_user='alice')
        remote.build()
    assert '--run-user' not in remote.built_cmd


def test_run_user_is_left_out_when_linbo_remote_cannot_be_run():
    with patch('linuxmusterTools.linbo.linbo_sync.subprocess.run', side_effect=FileNotFoundError):
        remote = LinboRemote(clients=['10.0.0.5'], cmd='reboot', run_user='alice')
        remote.build()
    assert '--run-user' not in remote.built_cmd


def test_without_run_user_the_command_is_unchanged():
    remote = LinboRemote(clients=['10.0.0.5'], cmd='reboot')
    remote.build()
    assert remote.built_cmd == '/usr/sbin/linbo-remote -i 10.0.0.5 -c reboot'


def test_run_user_is_not_passed_for_an_onboot_command():
    with help_output('--run-user\n'):
        remote = LinboRemote(clients=['10.0.0.5'], cmd='reboot', run_user='alice', onboot=True)
        remote.build()
    assert '--run-user' not in remote.built_cmd


@pytest.mark.parametrize('user', ['a b', 'a;rm -rf', '', 'x' * 65, 'a\nb', 'bob\n', '$(id)'])
def test_an_unsafe_run_user_is_refused(user):
    with pytest.raises(LinboRemoteParameterError):
        LinboRemote(clients=['10.0.0.5'], cmd='reboot', run_user=user).build()


def test_a_failed_probe_is_asked_again():
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs.get('timeout'))
        if len(calls) == 1:
            raise FileNotFoundError
        return MagicMock(stdout='--run-user\n')

    with patch('linuxmusterTools.linbo.linbo_sync.subprocess.run', side_effect=run):
        assert supports_run_user() is False
        assert supports_run_user() is True
        assert supports_run_user() is True

    assert len(calls) == 2
    assert all(timeout for timeout in calls)


def test_a_hanging_probe_is_not_a_support():
    import subprocess

    with patch('linuxmusterTools.linbo.linbo_sync.subprocess.run',
               side_effect=subprocess.TimeoutExpired('linbo-remote', 5)):
        assert supports_run_user() is False
