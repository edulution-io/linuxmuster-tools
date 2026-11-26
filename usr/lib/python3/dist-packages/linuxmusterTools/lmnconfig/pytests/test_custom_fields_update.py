import threading

import pytest

import linuxmusterTools.lmnconfig.webui as webui_module
from linuxmusterTools.lmnconfig import ConfigChangedError
from linuxmusterTools.lmnconfig.webui import CustomFieldsConfig
from linuxmusterTools.lmnfile import LMNFile


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / 'custom_fields.yml'
    monkeypatch.setattr(CustomFieldsConfig, 'path', staticmethod(lambda school: path))
    monkeypatch.setattr('linuxmusterTools.lmnconfig.locking.LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('linuxmusterTools.lmnfile.lmnfile.ALLOWED_PATHS', [str(tmp_path)])
    monkeypatch.setattr(webui_module, '_CACHE', {})

    def read():
        with LMNFile(path, 'r') as f:
            return f.read()

    return read


def test_omitted_settings_are_kept(config):
    CustomFieldsConfig.update('abc', {'proxyAddresses': {'teachers': {'show': True, 'editable': True}}})
    CustomFieldsConfig.update('abc', {'proxyAddresses': {'teachers': {'title': 'Mail'}}})
    CustomFieldsConfig.update('abc', {'custom': {'students': {'1': {'show': True}}}})
    CustomFieldsConfig.update('abc', {'custom': {'students': {'1': {'title': 'Locker'}}}})
    data = config()
    assert data['proxyAddresses']['teachers'] == {'show': True, 'editable': True, 'title': 'Mail'}
    assert data['custom']['students']['1'] == {'show': True, 'title': 'Locker'}


def test_a_change_based_on_an_old_version_is_refused(config):
    etag = CustomFieldsConfig.etag('abc')
    CustomFieldsConfig.update('abc', {'custom': {'students': {'1': {'title': 'A'}}}}, etag=etag)
    with pytest.raises(ConfigChangedError):
        CustomFieldsConfig.update('abc', {'custom': {'students': {'1': {'title': 'B'}}}}, etag=etag)
    assert config()['custom']['students']['1']['title'] == 'A'


def test_parallel_updates_keep_both_changes(config):
    changes = [{'custom': {'students': {str(number): {'title': f'T{number}'}}}} for number in range(1, 6)]
    threads = [threading.Thread(target=CustomFieldsConfig.update, args=('abc', change)) for change in changes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(config()['custom']['students']) == ['1', '2', '3', '4', '5']
