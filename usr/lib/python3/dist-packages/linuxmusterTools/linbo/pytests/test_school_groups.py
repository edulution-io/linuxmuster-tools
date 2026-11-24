"""
Tests for school-qualified LINBO group ids: the id helpers, the school scope of
LinboConfigManager, the Group line of a qualified start.conf, and the call sites
that turn a group of devices.csv into an id (list_workstations, the change
tracker and LinboRemote).
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import linuxmusterTools.linbo.changes as changes_module
import linuxmusterTools.linbo.config as config_module
from linuxmusterTools.linbo.config import LinboConfigManager, list_workstations, set_group_line
from linuxmusterTools.linbo.group_ids import (
    LINBO_GROUP_SEPARATOR,
    get_linbo_group_id,
    split_linbo_group_id,
)
from linuxmusterTools.linbo.linbo_sync import LinboRemote

CONTENT = "[LINBO]\nServer = 10.0.0.1\nGroup = raum101\n\n[OS]\nBaseImage=ubuntu.qcow2\n"
LISTED_CONTENT = (
    "[OS]\nBaseImage=ubuntu.qcow2\nRoot=/dev/sda1\nSyncEnabled=yes\nNewEnabled=no\nStartEnabled=yes\n"
)
OS_CONFIG = [{'baseimage': 'ubuntu.qcow2'}, {'baseimage': 'win.qcow2'}]


def write_conf(tmp_path, group_id, content=CONTENT):
    (tmp_path / f'start.conf.{group_id}').write_text(content)


# ── id helpers ───────────────────────────────────────────────────────────


@pytest.mark.parametrize('school, group, expected', [
    ('default-school', 'raum101', 'raum101'),
    ('default-school', 'win11_edu', 'win11_edu'),
    ('abc', 'raum101', 'abc__raum101'),
    ('gs-nord', 'win11_edu', 'gs-nord__win11_edu'),
    ('a', 'b-x', 'a__b-x'),
    ('a-b', 'x', 'a-b__x'),
    (None, 'raum101', 'raum101'),
])
def test_get_linbo_group_id(school, group, expected):
    assert get_linbo_group_id(school, group) == expected


@pytest.mark.parametrize('group_id, expected', [
    ('raum101', ('default-school', 'raum101')),
    ('win11_edu', ('default-school', 'win11_edu')),
    ('abc__raum101', ('abc', 'raum101')),
    ('abc__win11_edu', ('abc', 'win11_edu')),
    ('abc___raum', ('abc', '_raum')),
    ('abc__raum__101', ('abc', 'raum__101')),
])
def test_split_linbo_group_id(group_id, expected):
    assert split_linbo_group_id(group_id) == expected


def test_separator_matches_base7_and_linbo7():
    assert LINBO_GROUP_SEPARATOR == '__'


# ── scope of the manager ─────────────────────────────────────────────────


@pytest.fixture
def two_schools(tmp_path):
    for group_id in ('raum101', 'lab', 'abc__raum101', 'abc__win11_edu', 'xyz__raum101'):
        write_conf(tmp_path, group_id)


def test_manager_without_school_lists_every_group(two_schools):
    assert LinboConfigManager().group_ids == [
        'abc__raum101', 'abc__win11_edu', 'lab', 'raum101', 'xyz__raum101',
    ]


def test_manager_of_default_school_lists_plain_groups_only(two_schools):
    assert LinboConfigManager('default-school').group_ids == ['lab', 'raum101']


def test_manager_of_a_school_lists_its_own_groups_only(two_schools):
    assert LinboConfigManager('abc').group_ids == ['abc__raum101', 'abc__win11_edu']
    assert LinboConfigManager('xyz').group_ids == ['xyz__raum101']
    assert LinboConfigManager('nobody').group_ids == []


def test_school_name_that_prefixes_another_is_not_confused(tmp_path):
    write_conf(tmp_path, 'ab__raum')
    write_conf(tmp_path, 'abc__raum')
    assert LinboConfigManager('ab').group_ids == ['ab__raum']


def test_load_raw_startconfs_skips_foreign_groups(two_schools):
    ids = ['abc__raum101', 'xyz__raum101', 'raum101']
    assert [r['id'] for r in LinboConfigManager('abc').load_raw_startconfs(ids)] == ['abc__raum101']
    assert len(LinboConfigManager().load_raw_startconfs(ids)) == 3


def test_load_linbo_startconf_of_a_foreign_group_is_none(two_schools):
    assert LinboConfigManager('abc').load_linbo_startconf('xyz__raum101') is None


def test_write_to_a_foreign_group_is_refused(tmp_path):
    with pytest.raises(ValueError):
        LinboConfigManager('abc').write_raw_startconf('xyz__raum101', CONTENT)
    with pytest.raises(ValueError):
        LinboConfigManager('abc').write_raw_startconf('raum101', CONTENT)
    assert not (tmp_path / 'start.conf.xyz__raum101').exists()
    assert not (tmp_path / 'start.conf.raum101').exists()


def test_delete_of_a_foreign_group_is_refused(two_schools, tmp_path):
    with pytest.raises(ValueError):
        LinboConfigManager('abc').delete_startconf('xyz__raum101')
    assert (tmp_path / 'start.conf.xyz__raum101').is_file()
    LinboConfigManager('abc').delete_startconf('abc__raum101')
    assert not (tmp_path / 'start.conf.abc__raum101').exists()


@pytest.mark.parametrize('method, args', [
    ('list_startconf_backups', ()),
    ('restore_startconf_backup', (1,)),
    ('delete_startconf_backup', (1,)),
    ('read_vdi_config', ()),
    ('write_vdi_config', ({},)),
    ('delete_vdi_config', ()),
])
def test_backups_and_vdi_of_a_foreign_group_are_refused(two_schools, method, args):
    with pytest.raises(ValueError):
        getattr(LinboConfigManager('abc'), method)('xyz__raum101', *args)


# ── the Group line of a qualified start.conf ─────────────────────────────


def test_write_sets_group_line_of_a_qualified_id(tmp_path):
    LinboConfigManager('abc').write_raw_startconf('abc__raum101', CONTENT)
    written = (tmp_path / 'start.conf.abc__raum101').read_text()
    assert 'Group = abc__raum101\n' in written
    assert written.count('Group') == 1
    assert 'Server = 10.0.0.1\n' in written and 'BaseImage=ubuntu.qcow2\n' in written


def test_write_keeps_the_content_of_a_plain_group_verbatim(tmp_path):
    LinboConfigManager('default-school').write_raw_startconf('raum101', CONTENT)
    assert (tmp_path / 'start.conf.raum101').read_text() == CONTENT
    LinboConfigManager().write_raw_startconf('lab', 'whatever\n')
    assert (tmp_path / 'start.conf.lab').read_text() == 'whatever\n'


@pytest.mark.parametrize('line', ['Group=raum101', 'Group = raum101', 'group  =  raum101', '  Group =raum101'])
def test_set_group_line_replaces_any_spacing(line):
    content = f'[LINBO]\nServer = 10.0.0.1\n{line}\nCache = /dev/sda4\n'
    result = set_group_line(content, 'abc__raum101')
    assert result == '[LINBO]\nServer = 10.0.0.1\nGroup = abc__raum101\nCache = /dev/sda4\n'


def test_set_group_line_adds_a_missing_line_to_the_linbo_section():
    assert set_group_line('[LINBO]\nServer = 10.0.0.1\n', 'abc__raum101') == \
        '[LINBO]\nGroup = abc__raum101\nServer = 10.0.0.1\n'


def test_set_group_line_without_linbo_section_is_unchanged():
    assert set_group_line('[OS]\nBaseImage=x\n', 'abc__raum101') == '[OS]\nBaseImage=x\n'


def test_set_group_line_changes_only_the_first_group_line():
    content = '[LINBO]\nGroup = a\n[OS]\nGroup = b\n'
    assert set_group_line(content, 'abc__x') == '[LINBO]\nGroup = abc__x\n[OS]\nGroup = b\n'


# ── call sites ───────────────────────────────────────────────────────────


def fake_devices(devices):
    class FakeDevices:
        def __init__(self, school):
            self.school = school

        def filter(self, groups):
            return devices

    return FakeDevices


def test_list_workstations_of_a_school_is_keyed_by_group_id(tmp_path, monkeypatch):
    write_conf(tmp_path, 'abc__raum101', LISTED_CONTENT)
    write_conf(tmp_path, 'raum101', LISTED_CONTENT)
    devices = [{'hostname': 'pc01', 'group': 'raum101', 'pxeFlag': '1'}]
    monkeypatch.setattr(config_module, 'Devices', fake_devices(devices))

    workstations = list_workstations(school='abc')

    assert list(workstations) == ['abc__raum101']
    assert workstations['abc__raum101']['grp'] == 'abc__raum101'
    assert workstations['abc__raum101']['hosts'][0]['hostname'] == 'abc-pc01'
    assert workstations['abc__raum101']['hosts'][0]['group'] == 'raum101'


def test_list_workstations_of_a_school_ignores_the_plain_group_file(tmp_path, monkeypatch):
    write_conf(tmp_path, 'raum101')
    devices = [{'hostname': 'pc01', 'group': 'raum101', 'pxeFlag': '1'}]
    monkeypatch.setattr(config_module, 'Devices', fake_devices(devices))
    assert list_workstations(school='abc') == {}


def test_list_workstations_of_default_school_is_unchanged(tmp_path, monkeypatch):
    write_conf(tmp_path, 'raum101', LISTED_CONTENT)
    devices = [{'hostname': 'pc01', 'group': 'raum101', 'pxeFlag': '1'}]
    monkeypatch.setattr(config_module, 'Devices', fake_devices(devices))
    workstations = list_workstations()
    assert list(workstations) == ['raum101']
    assert workstations['raum101']['hosts'][0]['hostname'] == 'pc01'


def test_change_tracker_matches_group_ids_of_its_school(tmp_path, monkeypatch):
    startconf = tmp_path / 'start.conf.abc__room1'
    startconf.write_text('x')
    old = time.time() - 3600
    os.utime(startconf, (old, old))
    devices = SimpleNamespace(
        load=lambda: setattr(devices, 'csv_mtime', None),
        groups=['room1'],
        macs=[],
        csv_mtime=None,
    )
    grub_reader = SimpleNamespace(
        list_grub_cfg_ids=lambda: ['abc__room1', 'xyz__room1', 'room1'],
        get_cfg_mtime=lambda group: None,
    )
    manager = SimpleNamespace(group_ids=['abc__room1', 'xyz__room1', 'room1'])
    monkeypatch.setattr(changes_module, 'Devices', lambda school: devices)
    monkeypatch.setattr(changes_module, 'LinboConfigManager', lambda: manager)
    monkeypatch.setattr(changes_module, 'LinboGrubReader', lambda: grub_reader)
    monkeypatch.setattr(changes_module, 'DHCP_SUBNETS_PATH', tmp_path / 'subnets.conf')
    monkeypatch.setattr(changes_module, 'LINBO_PATH', str(tmp_path))

    changes = changes_module.LinboChangeTracker('abc').get_changes('0')

    assert changes['startConfsChanged'] == ['abc__room1']
    assert changes['configsChanged'] == ['abc__room1']


def make_fake_devices(devices_list):
    fake = MagicMock()
    fake.devices = devices_list
    return fake


def test_linbo_remote_resolves_group_to_the_id_of_its_school():
    seen = []

    def read_config(group):
        seen.append(group)
        return OS_CONFIG

    remote = LinboRemote(group='raum101', cmd='sync:2', school='abc')
    with patch('linuxmusterTools.linbo.linbo_sync.lr.getval', return_value=['abc']):
        with patch('linuxmusterTools.linbo.linbo_sync.read_config', side_effect=read_config):
            remote.build()

    assert seen == ['abc__raum101']


def test_linbo_remote_resolves_room_and_clients_to_ids_of_the_school():
    devices = [{'ip': '10.0.0.5', 'hostname': 'pc001', 'group': 'raum101', 'room': 'room1'}]
    seen = []

    def read_config(group):
        seen.append(group)
        return OS_CONFIG

    for kwargs in ({'room': 'room1'}, {'clients': ['abc-pc001']}):
        seen.clear()
        remote = LinboRemote(cmd='sync:2', school='abc', **kwargs)
        with patch('linuxmusterTools.linbo.linbo_sync.lr.getval', return_value=['abc']):
            with patch('linuxmusterTools.linbo.linbo_sync.Devices', return_value=make_fake_devices(devices)):
                with patch('linuxmusterTools.linbo.linbo_sync.read_config', side_effect=read_config):
                    remote.build()
        assert seen == ['abc__raum101']


def test_linbo_remote_of_default_school_keeps_the_plain_group():
    seen = []
    remote = LinboRemote(group='raum101', cmd='sync:2')
    with patch('linuxmusterTools.linbo.linbo_sync.read_config', side_effect=lambda g: seen.append(g) or OS_CONFIG):
        remote.build()
    assert seen == ['raum101']


# ── a group containing the separator cannot name a group of another school ──


@pytest.mark.parametrize('school', ['default-school', 'abc', None])
def test_a_group_with_the_separator_has_no_id(school):
    with pytest.raises(ValueError):
        get_linbo_group_id(school, 'abc__raum101')


def test_the_default_school_manager_does_not_own_a_qualified_id(two_schools):
    manager = LinboConfigManager('default-school')
    assert not manager.owns('abc__raum101')
    assert not manager.owns('default-school__x')
    assert manager.owns('raum101')


def test_linbo_remote_refuses_a_group_with_the_separator():
    from linuxmusterTools.linbo.linbo_sync import LinboRemoteParameterError

    with patch('linuxmusterTools.linbo.linbo_sync.lr.getval', return_value=['default-school']):
        with pytest.raises(LinboRemoteParameterError):
            LinboRemote(group='abc__raum101', cmd='sync:1', school='default-school').build()


def test_set_group_line_keeps_crlf_line_endings():
    content = '[LINBO]\r\nGroup = a\r\nCache = /dev/sda4\r\n'
    assert set_group_line(content, 'abc__a') == '[LINBO]\r\nGroup = abc__a\r\nCache = /dev/sda4\r\n'


def test_try_get_linbo_group_id_skips_a_group_without_a_valid_id():
    from linuxmusterTools.linbo.group_ids import try_get_linbo_group_id

    assert try_get_linbo_group_id('abc', 'raum101') == 'abc__raum101'
    assert try_get_linbo_group_id('default-school', 'raum__1') is None


@pytest.mark.parametrize('school', ['default-school', 'abc', None])
@pytest.mark.parametrize('group', ['', ' ', '\t', None])
def test_an_empty_group_has_no_id(school, group):
    from linuxmusterTools.linbo.group_ids import try_get_linbo_group_id

    with pytest.raises(ValueError):
        get_linbo_group_id(school, group)
    assert try_get_linbo_group_id(school, group) is None


def test_a_device_with_an_invalid_group_is_skipped_by_the_workstation_listing(tmp_path, monkeypatch):
    write_conf(tmp_path, 'raum101', LISTED_CONTENT)
    write_conf(tmp_path, 'raum__1', LISTED_CONTENT)
    devices = [
        {'hostname': 'pc01', 'group': 'raum101', 'pxeFlag': '1'},
        {'hostname': 'pc02', 'group': 'raum__1', 'pxeFlag': '1'},
    ]
    monkeypatch.setattr(config_module, 'Devices', fake_devices(devices))

    assert list(list_workstations(school='default-school')) == ['raum101']


def test_linbo_remote_skips_devices_with_an_invalid_group():
    devices = [
        {'ip': '10.0.0.5', 'hostname': 'pc01', 'group': 'raum101', 'room': 'r1'},
        {'ip': '10.0.0.6', 'hostname': 'pc02', 'group': 'raum__1', 'room': 'r1'},
    ]
    with patch('linuxmusterTools.linbo.linbo_sync.lr.getval', return_value=['default-school']):
        with patch('linuxmusterTools.linbo.linbo_sync.Devices', return_value=SimpleNamespace(devices=devices)):
            remote = LinboRemote(room='r1', cmd='sync:1')
            assert remote._target_groups() == {'raum101'}


# ── dnsmasq proxy export ─────────────────────────────────────────────────


def _dnsmasq(school=None, hosts=None):
    from linuxmusterTools.linbo.dhcp import LinboDhcpExporter

    hosts = hosts or [
        {'pxeEnabled': True, 'mac': 'aa:bb:cc:00:00:01', 'group': 'raum101'},
        {'pxeEnabled': True, 'mac': 'aa:bb:cc:00:00:02', 'group': 'raum101'},
    ]
    kwargs = {} if school is None else {'school': school}
    return LinboDhcpExporter().generate_dnsmasq_proxy(hosts, server_ip='10.0.0.1', **kwargs)


def test_dnsmasq_proxy_default_school_keeps_the_plain_group():
    config = _dnsmasq()
    assert 'dhcp-option=tag:raum101,40,raum101' in config
    assert 'dhcp-host=aa:bb:cc:00:00:01,set:raum101' in config


def test_dnsmasq_proxy_qualifies_the_group_of_another_school():
    config = _dnsmasq('abc')
    assert 'dhcp-option=tag:abc__raum101,40,abc__raum101' in config
    assert 'dhcp-host=aa:bb:cc:00:00:01,set:abc__raum101' in config
    assert 'dhcp-host=aa:bb:cc:00:00:02,set:abc__raum101' in config
    assert config.count('40,') == 1
    assert '40,raum101' not in config


def test_dnsmasq_proxy_skips_a_host_whose_group_has_no_valid_id():
    config = _dnsmasq('abc', [
        {'pxeEnabled': True, 'mac': 'aa:bb:cc:00:00:01', 'group': 'raum101'},
        {'pxeEnabled': True, 'mac': 'aa:bb:cc:00:00:02', 'group': 'raum__1'},
        {'pxeEnabled': True, 'mac': 'aa:bb:cc:00:00:03', 'group': ''},
    ])
    assert 'aa:bb:cc:00:00:01' in config
    assert 'aa:bb:cc:00:00:02' not in config
    assert 'aa:bb:cc:00:00:03' not in config
