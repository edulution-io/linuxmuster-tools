import pytest

from linuxmusterTools.accounts import accounts
from linuxmusterTools.accounts import (
    AccountError, AccountExistsError, AccountNotFoundError, create_account, delete_account,
)


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(accounts, '_run', recorded.append)
    monkeypatch.setattr(accounts, 'get_account', lambda kind, name: {'cn': name})
    monkeypatch.setattr(accounts, '_set_password', lambda *a: None)
    return recorded


def test_create_never_passes_the_password(calls):
    assert create_account('schooladministrator', 'a.b', school='abc', password='S3cret!') == 'S3cret!'
    assert calls == [['sophomorix-admin', '--create-school-admin', 'a.b', '--random-passwd-show', '--school', 'abc']]


@pytest.mark.parametrize('kind, name, school', [
    ('globalbinduser', '-x', None), ('globalbinduser', 'A', None), ('globalbinduser', 'a b', None),
    ('globalbinduser', 'a' * 21, None), ('globalbinduser', 'abc', 'school'), ('schoolbinduser', 'abc', None),
])
def test_create_refused(calls, kind, name, school):
    with pytest.raises(ValueError):
        create_account(kind, name, school=school, password='x')
    assert calls == []


def test_an_account_without_password_is_removed(calls, monkeypatch):
    def fail(*a):
        raise RuntimeError('too simple')
    monkeypatch.setattr(accounts, '_set_password', fail)
    with pytest.raises(AccountError):
        create_account('globaladministrator', 'newadmin', password='x')
    assert calls[-1] == ['sophomorix-admin', '--kill', 'newadmin']


@pytest.mark.parametrize('name', ['global-admin', 'Global-Admin', 'pgmadmin', 'global-binduser', '-x'])
def test_protected(calls, name):
    with pytest.raises(ValueError):
        delete_account('globaladministrator', name)
    assert calls == []


def test_delete(calls, monkeypatch):
    delete_account('globaladministrator', 'old')
    assert calls == [['sophomorix-admin', '--kill', 'old']]
    monkeypatch.setattr(accounts, 'get_account', lambda kind, name: {})
    with pytest.raises(AccountNotFoundError):
        delete_account('globaladministrator', 'student1')


def test_existing_name():
    with pytest.raises(AccountExistsError):
        accounts._run(['echo', 'ERROR: Object x exists already in AD'])
