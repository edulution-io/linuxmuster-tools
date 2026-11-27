"""
Read and write the settings of a school (school.conf).

The master file shipped by sophomorix tells which sections and keys exist and
what their defaults are. Nothing else can be written: sophomorix refuses to
run with a section or a key it does not know.

sophomorix passes some of these values to a shell running as root, e.g.
PRINTSERVER to sed and DICE_* to diceware, so every value is checked against
a strict pattern before it reaches the file.
"""

import os
import re

from linuxmusterTools.lmnfile import LMNFile
from .locking import check_unchanged, file_etag, locked


SCHOOL_CONF_MASTER = '/usr/share/sophomorix/devel/master/school.conf.master'
SCHOOL_CONF_DIR = '/etc/linuxmuster/sophomorix'

TRUE_VALUES = ('true', 'yes')
FALSE_VALUES = ('false', 'no')

# Keys only a global-administrator may change: the first names a program
# sophomorix runs as root, the second grants permissions.
RESTRICTED_KEYS = ('FILTERSCRIPT', 'WEBUI_PERMISSIONS')

RANDOM_PWD_CHOICES = ('TRUE', 'FALSE', 'birthdate', 'dice')

# Keys sophomorix only accepts with one of these values, see
# SophomorixSambaAD.pm. An other value stops every sophomorix-check.
STRING_CHOICES = {
    'MAIL_LOCAL_PART_SCHEME': ('', 'firstname', 'lastname', 'firstname.lastname', 'lastname.firstname', 'manual'),
}

# Minimum and maximum of the numeric keys, quotas accept -1 (unlimited).
INT_RANGES = {
    'QUOTA_DEFAULT_GLOBAL': (-1, 2**31 - 1),
    'QUOTA_DEFAULT_SCHOOL': (-1, 2**31 - 1),
    'MAILQUOTA_DEFAULT': (-1, 2**31 - 1),
    'CLOUDQUOTA_PERCENTAGE': (0, 100),
    'SURNAME_CHARS': (0, 20),
    'FIRSTNAME_CHARS': (0, 20),
    'LOGIN_MAXLEN': (0, 20),
    'PWD_LENGTH': (4, 64),
    'DICE_WORDS': (1, 20),
    'TOLERATION_TIME': (0, 3650),
    'DEACTIVATION_TIME': (0, 3650),
}

# Everything the config parsers, a shell or LaTeX could interpret is left out.
_PLAIN = r'[\w .,:;@=+*/()\[\]?!%-]*'
_TEXT = r'[\w .,:;@=+*/()\[\]?!%&~-]*'

PATTERNS = {
    'PRINTSERVER': r'([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?)?',
    'LANG': r'[A-Za-z_-]*',
    'DICE_LANG': r'[A-Za-z0-9_][A-Za-z0-9_-]*',
    'DICE_SEPARATOR': r'[._+:=-]?',
    'LOGIN_SEPARATOR': r'[._-]?',
    'LOGIN_REGEX': r'\^[\[\]A-Za-z0-9._{},+*?\\-]*\$',
    'MAILTYPE': r'[a-z]+',
    'MAILDOMAIN': r'[A-Za-z0-9.-]*',
    'ENCODING': r'[A-Za-z0-9_-]+',
    'FILTERSCRIPT': r'---|/[A-Za-z0-9._/-]+',
    'WEBUI_PERMISSIONS': r'[A-Za-z0-9:._,/ -]*',
    'DEFAULT_NONRANDOM_PWD': r'[A-Za-z0-9!@%+*=?.,_-]*',
}

_DESCRIPTION_KEY = re.compile(r'ADMINS_PRINT|SCHOOL_LONGNAME|URL[A-Z]+_PRINT')


class SchoolSettingsError(ValueError):
    """Raised with the list of every refused setting."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors))


def _parse_master(path):
    """
    :return: {section: {key: {'type', 'default', 'restricted'}}}
    """

    schema = {}
    section = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('[') and line.endswith(']'):
                section = line[1:-1]
                schema[section] = {}
                continue
            key, separator, value = line.partition('=')
            if section is None or not separator:
                continue
            key, value = key.strip(), re.sub(r'\s+#.*$', '', value).strip()

            if value.startswith('BOOLEAN|'):
                entry = {'type': 'boolean', 'default': value.split('|', 1)[1].upper() == 'TRUE'}
            elif value.startswith('MULTI|'):
                entry = {'type': 'choice', 'default': value.split('|', 1)[1], 'choices': list(RANDOM_PWD_CHOICES)}
            elif key in STRING_CHOICES:
                entry = {'type': 'choice', 'default': value, 'choices': list(STRING_CHOICES[key])}
            elif key in INT_RANGES:
                entry = {'type': 'integer', 'default': int(value or 0)}
                entry['minimum'], entry['maximum'] = INT_RANGES[key]
            else:
                entry = {'type': 'string', 'default': value}
            entry['restricted'] = key in RESTRICTED_KEYS
            schema[section][key] = entry
    return {name: keys for name, keys in schema.items() if keys}


class SchoolSettings:
    """
    The settings of one school.

    :param school: School name
    """

    def __init__(self, school='default-school', master=SCHOOL_CONF_MASTER):
        prefix = '' if school == 'default-school' else f'{school}.'
        self.school = school
        self.path = os.path.join(SCHOOL_CONF_DIR, school, f'{prefix}school.conf')
        self.schema = _parse_master(master)

    @staticmethod
    def _to_python(entry, value):
        value = str(value).strip()
        if entry['type'] == 'boolean':
            return value.lower() in TRUE_VALUES
        if entry['type'] == 'integer':
            try:
                return int(value)
            except ValueError:
                return entry['default']
        if entry['type'] == 'choice' and value.lower() in TRUE_VALUES + FALSE_VALUES:
            return 'TRUE' if value.lower() in TRUE_VALUES else 'FALSE'
        return value

    def read(self):
        """
        :return: Every known setting, with its default if school.conf does not set it
        :rtype: dict
        """

        stored = {}
        if os.path.isfile(self.path):
            with LMNFile(self.path, 'r', convert_values=False) as f:
                stored = {name: dict(options) for name, options in f.data.items() if hasattr(options, 'items')}

        return {
            section: {
                key: self._to_python(entry, stored.get(section, {}).get(key, entry['default']))
                for key, entry in keys.items()
            }
            for section, keys in self.schema.items()
        }

    def _normalise(self, entry, key, value):
        """
        :return: The value as written to school.conf
        :raises ValueError: value not allowed for this key
        """

        if entry['type'] == 'boolean':
            if not isinstance(value, bool):
                raise ValueError('must be a boolean')
            return 'TRUE' if value else 'FALSE'

        if entry['type'] == 'integer':
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError('must be an integer')
            if not entry['minimum'] <= value <= entry['maximum']:
                raise ValueError(f"must be between {entry['minimum']} and {entry['maximum']}")
            return str(value)

        if not isinstance(value, str):
            raise ValueError('must be a string')

        if entry['type'] == 'choice':
            if value not in entry['choices']:
                raise ValueError(f"must be one of {', '.join(entry['choices'])}")
            return value

        pattern = PATTERNS.get(key, _TEXT if _DESCRIPTION_KEY.match(key) else _PLAIN)
        if len(value) > 250 or not re.fullmatch(pattern, value):
            raise ValueError('contains characters which are not allowed')
        if value != value.strip():
            raise ValueError('must not start or end with a space')
        if key == 'LOGIN_REGEX':
            try:
                re.compile(value)
            except re.error as error:
                raise ValueError(f'is no valid regular expression: {error}') from error
        return value

    def validate(self, changes, allow_restricted=False):
        """
        :param changes: {section: {key: value}}, partial
        :param allow_restricted: Whether RESTRICTED_KEYS may be changed
        :return: The changes as written to school.conf
        :raises SchoolSettingsError: naming every refused setting
        """

        result, errors = {}, []
        current = self.read()

        for section, options in changes.items():
            if section not in self.schema:
                errors.append(f'Unknown section {section}')
                continue
            for key, value in options.items():
                entry = self.schema[section].get(key)
                if entry is None:
                    errors.append(f'Unknown setting {section}/{key}')
                    continue
                # Sending back what was read must not be refused.
                if value == current[section][key]:
                    continue
                if entry['restricted'] and not allow_restricted:
                    errors.append(f'{section}/{key} can only be changed by a global-administrator')
                    continue
                try:
                    result.setdefault(section, {})[key] = self._normalise(entry, key, value)
                except ValueError as error:
                    errors.append(f'{section}/{key} {error}')

        if errors:
            raise SchoolSettingsError(errors)
        return result

    def etag(self):
        """
        :return: ETag of school.conf, see update()
        """

        return file_etag(self.path)

    def update(self, changes, allow_restricted=False, etag=None):
        """
        Write some settings, the others are left untouched.

        :param etag: ETag of the file the changes are based on, see etag()
        :return: All settings, see read()
        :raises SchoolSettingsError: nothing is written if one setting is refused
        :raises ConfigChangedError: school.conf changed since etag was read
        """

        # From reading to writing, the values sent back are compared with the
        # file they will be written to
        with locked(self.path):
            check_unchanged(self.path, etag)
            accepted = self.validate(changes, allow_restricted=allow_restricted)
            if accepted:
                with LMNFile(self.path, 'w', convert_values=False) as f:
                    f.backup()
                    f.write(accepted)
            return self.read()
