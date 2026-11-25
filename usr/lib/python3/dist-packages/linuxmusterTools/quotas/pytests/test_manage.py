import pytest

from linuxmusterTools.quotas import manage
from linuxmusterTools.quotas.manage import build_user_quota_args, set_user_quota, QuotaError


def test_args():
    assert build_user_quota_args(
        'max', 'abc', [{'share': 'abc', 'quota': 500, 'comment': 'video'}, {'share': 'linuxmuster-global', 'quota': None}],
        {'quota': 100, 'comment': None},
    ) == ['sophomorix-user', '--user', 'max', '--quota', 'abc:500:video,linuxmuster-global:---:---', '--mailquota', '100:---']


@pytest.mark.parametrize('quotas', [
    [], [{'share': 'other', 'quota': 1}], [{'share': 'abc', 'quota': -2}], [{'share': 'abc', 'quota': True}],
    [{'share': 'abc', 'quota': 1, 'comment': 'a,b'}], [{'share': 'abc', 'quota': 1, 'comment': 'a:b'}],
])
def test_refused(quotas):
    with pytest.raises(ValueError):
        build_user_quota_args('max', 'abc', quotas)


@pytest.mark.parametrize('apply, commands', [(True, 2), (False, 1)])
def test_apply(monkeypatch, apply, commands):
    calls = []
    monkeypatch.setattr(manage, '_run', calls.append)
    set_user_quota('max', 'abc', [{'share': 'abc', 'quota': 1}], apply=apply)
    assert len(calls) == commands


def test_an_error_in_the_output_is_raised():
    with pytest.raises(QuotaError):
        manage._run(['echo', 'ERROR: no such user'])
    with pytest.raises(QuotaError):
        manage._run(['false'])
