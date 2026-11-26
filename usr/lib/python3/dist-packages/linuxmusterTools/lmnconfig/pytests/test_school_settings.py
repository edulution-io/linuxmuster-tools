import pytest

import linuxmusterTools.lmnconfig.school_settings as module
from linuxmusterTools.lmnconfig.school_settings import SchoolSettings, SchoolSettingsError

MASTER = """# comment
[school]
\tSCHOOL_LONGNAME=Linuxmuster School
\tPRINTSERVER =
\tURLMAIL_PRINT=
[role.student]
\tQUOTA_DEFAULT_SCHOOL=1500
\tMAIL_LOCAL_PART_SCHEME=
        CLOUDQUOTA_PERCENTAGE=100
\tWEBUI_PERMISSIONS=
[userfile.students.csv]
\tFILTERSCRIPT=---
\tENCODING_FORCE=BOOLEAN|FALSE
\tRANDOM_PWD=MULTI|TRUE        # might be TRUE|FALSE|birthdate|dice
\tDICE_LANG=de
\tDICE_SEPARATOR=.
\tLOGIN_REGEX=^[a-z0-9._-]+$
[type.room]
\t# nothing
"""


@pytest.fixture
def settings(tmp_path, monkeypatch):
    master = tmp_path / 'master'
    master.write_text(MASTER)
    school = tmp_path / 'default-school'
    school.mkdir()
    (school / 'school.conf').write_text(
        '# keep me\n[school]\n\tSCHOOL_LONGNAME=Test\n[userfile.students.csv]\n\tENCODING_FORCE=no\n\tRANDOM_PWD=yes\n'
    )
    monkeypatch.setattr(module, 'SCHOOL_CONF_DIR', str(tmp_path))
    monkeypatch.setattr('linuxmusterTools.lmnconfig.locking.LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('linuxmusterTools.lmnfile.lmnfile.ALLOWED_PATHS', [str(tmp_path)])
    return SchoolSettings('default-school', master=str(master))


def test_read_merges_defaults_and_types(settings):
    data = settings.read()
    assert data['school'] == {'SCHOOL_LONGNAME': 'Test', 'PRINTSERVER': '', 'URLMAIL_PRINT': ''}
    assert data['role.student']['QUOTA_DEFAULT_SCHOOL'] == 1500
    assert data['userfile.students.csv']['ENCODING_FORCE'] is False
    assert data['userfile.students.csv']['RANDOM_PWD'] == 'TRUE'
    assert 'type.room' not in data


def test_update_keeps_the_rest(settings):
    data = settings.update({
        'school': {'PRINTSERVER': 'print-01.example.org', 'URLMAIL_PRINT': 'https://mail.example.org/?a=1&b=2'},
        'role.student': {'QUOTA_DEFAULT_SCHOOL': -1},
        'userfile.students.csv': {'ENCODING_FORCE': True, 'RANDOM_PWD': 'dice'},
    })
    assert data['school']['PRINTSERVER'] == 'print-01.example.org'
    assert data['school']['URLMAIL_PRINT'] == 'https://mail.example.org/?a=1&b=2'
    assert data['school']['SCHOOL_LONGNAME'] == 'Test'
    assert data['role.student']['QUOTA_DEFAULT_SCHOOL'] == -1
    content = open(settings.path).read()
    assert '# keep me' in content and 'ENCODING_FORCE = TRUE' in content


@pytest.mark.parametrize('section, key, value', [
    ('school', 'PRINTSERVER', 'x";id;"'), ('school', 'PRINTSERVER', 'x/g'), ('school', 'PRINTSERVER', '$(id)'),
    ('school', 'SCHOOL_LONGNAME', 'a\nB=c'), ('school', 'SCHOOL_LONGNAME', '`id`'), ('school', 'SCHOOL_LONGNAME', 'a # b'),
    ('school', 'UNKNOWN', 'x'), ('unknown', 'A', 'x'), ('school', 'PRINTSERVER', 5),
    ('role.student', 'QUOTA_DEFAULT_SCHOOL', '5'), ('role.student', 'QUOTA_DEFAULT_SCHOOL', True),
    ('role.student', 'CLOUDQUOTA_PERCENTAGE', 101),
    ('userfile.students.csv', 'ENCODING_FORCE', 'TRUE'), ('userfile.students.csv', 'RANDOM_PWD', 'x'),
    ('userfile.students.csv', 'DICE_LANG', 'de; id'), ('userfile.students.csv', 'DICE_LANG', '-h'),
    ('userfile.students.csv', 'DICE_SEPARATOR', "'"),
    ('userfile.students.csv', 'LOGIN_REGEX', '^(?{system("id")})$'), ('userfile.students.csv', 'LOGIN_REGEX', '^[a-z$'),
])
def test_refused(settings, section, key, value):
    before = open(settings.path).read()
    with pytest.raises(SchoolSettingsError):
        settings.update({section: {key: value}}, allow_restricted=True)
    assert open(settings.path).read() == before


def test_restricted_settings(settings):
    change = {'userfile.students.csv': {'FILTERSCRIPT': '/usr/local/bin/filter'}}
    with pytest.raises(SchoolSettingsError):
        settings.update(change)
    assert settings.update(change, allow_restricted=True)['userfile.students.csv']['FILTERSCRIPT'] == '/usr/local/bin/filter'
    # Unchanged values are accepted from everybody
    settings.update(change)


def test_nothing_is_written_if_one_setting_is_refused(settings):
    with pytest.raises(SchoolSettingsError) as error:
        settings.update({'school': {'PRINTSERVER': 'ok', 'SCHOOL_LONGNAME': '`'}})
    assert len(error.value.errors) == 1
    assert settings.read()['school']['PRINTSERVER'] == ''


@pytest.mark.parametrize('value, ok', [('', True), ('firstname.lastname', True), ('manual', True), ('givenname', False)])
def test_mail_local_part_scheme(settings, value, ok):
    changes = {'role.student': {'MAIL_LOCAL_PART_SCHEME': value}}
    if ok:
        assert settings.update(changes)['role.student']['MAIL_LOCAL_PART_SCHEME'] == value
    else:
        with pytest.raises(SchoolSettingsError):
            settings.update(changes)


def test_a_change_based_on_an_old_version_is_refused(settings):
    from linuxmusterTools.lmnconfig import ConfigChangedError

    etag = settings.etag()
    settings.update({'school': {'PRINTSERVER': 'print1'}}, etag=etag)
    with pytest.raises(ConfigChangedError):
        settings.update({'school': {'PRINTSERVER': 'print2'}}, etag=etag)
    assert settings.read()['school']['PRINTSERVER'] == 'print1'
    settings.update({'school': {'PRINTSERVER': 'print2'}}, etag=settings.etag())


def test_parallel_updates_keep_both_changes(settings):
    import threading

    threads = [
        threading.Thread(target=settings.update, args=({'school': {key: value}},))
        for key, value in (('PRINTSERVER', 'print1'), ('SCHOOL_LONGNAME', 'Other'), ('URLMAIL_PRINT', 'mail'))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    school = settings.read()['school']
    assert (school['PRINTSERVER'], school['SCHOOL_LONGNAME'], school['URLMAIL_PRINT']) == ('print1', 'Other', 'mail')

