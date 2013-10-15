# -*- coding: utf-8 -*-
'''
Install software from the FreeBSD ``ports(7)`` system

.. versionadded:: Hydrogen

This module allows you to install ports using ``BATCH=yes`` to bypass
configuration prompts. It is recommended to use the the :mod:`ports state
<salt.states.freebsdports>` to install ports, but it it also possible to use
this module exclusively from the command line.

.. code-block:: bash

    salt minion-id ports.config security/nmap IPV6=off
    salt minion-id ports.install security/nmap
'''

# Import python libs
import os
import re
import logging

# Import salt libs
import salt.utils
from salt._compat import string_types
from salt.exceptions import SaltInvocationError, CommandExecutionError

log = logging.getLogger(__name__)

def __virtual__():
    return 'ports' if __grains__.get('os', '') == 'FreeBSD' else False


def _check_portname(name):
    '''
    Check if portname is valid and whether or not the directory exists in the
    ports tree.
    '''
    if not isinstance(name, string_types) or '/' not in name:
        raise SaltInvocationError(
            'Invalid port name {0!r} (category required)'.format(name)
        )

    path = os.path.join('/usr/ports', name)
    if not os.path.isdir(path):
        raise SaltInvocationError('Path {0!r} does not exist'.format(path))

    return path


def _write_options(name, pkg, config):
    '''
    Writes a new OPTIONS file
    '''
    _check_portname(name)
    _root = '/var/db/ports'

    # New path: /var/db/ports/category_portname
    dirname = os.path.join(_root, name.replace('/', '_'))
    # Old path: /var/db/ports/portname
    old_dir = os.path.join(_root, name.split('/')[-1])

    if os.path.isdir(old_dir):
        dirname = old_dir

    if not os.path.isdir(dirname):
        try:
            os.makedirs(dirname)
        except OSError as exc:
            raise CommandExecutionError(
                'Unable to make {0}: {1}'.format(dirname, exc)
            )

    with salt.utils.fopen(os.path.join(dirname, 'options'), 'w') as fp_:
        fp_.write(
            '# This file was auto-generated by Salt (http://saltstack.com)\n'
            '# Options for {0}\n'
            '_OPTIONS_READ={0}\n'
            '_FILE_COMPLETE_OPTIONS_LIST={1}\n'
            .format(pkg, ' '.join(sorted(config)))
        )
        opt_tmpl = 'OPTIONS_FILE_{0}SET+={1}\n'
        for opt in sorted(config):
            fp_.write(
                opt_tmpl.format(
                    '' if config[opt] == 'on' else 'UN',
                    opt
                )
            )


def install(name, clean=True):
    '''
    Install a port from the ports tree. Installs using ``BATCH=yes`` for
    non-interactive building. To set config options for a given port, use
    :mod:`ports.config <salt.modules.freebsdports.config>`.

    clean : True
        If ``True``, cleans after installation. Equivalent to running ``make
        install clean BATCH=yes``.

    CLI Example:

    .. code-block:: bash

        salt '*' ports.install security/nmap
    '''
    portpath = _check_portname(name)
    old = __salt__['pkg.list_pkgs']()
    __salt__['cmd.run'](
        'make install{0} BATCH=yes'.format(' clean' if clean else ''),
        cwd=portpath
    )
    __context__.pop('pkg.list_pkgs', None)
    new = __salt__['pkg.list_pkgs']()
    return __salt__['pkg_resource.find_changes'](old, new)


def deinstall(name):
    '''
    De-install a port.

    CLI Example:

    .. code-block:: bash

        salt '*' ports.deinstall security/nmap
    '''
    portpath = _check_portname(name)
    old = __salt__['pkg.list_pkgs']()
    __salt__['cmd.run']('make deinstall BATCH=yes', cwd=portpath)
    __context__.pop('pkg.list_pkgs', None)
    new = __salt__['pkg.list_pkgs']()
    return __salt__['pkg_resource.find_changes'](old, new)


def rmconfig(name):
    '''
    Clear the cached options for the specified port; run a ``make rmconfig``

    name
        The name of the port to clear

    CLI Example:

    .. code-block:: bash

        salt '*' ports.rmconfig security/nmap
    '''
    portpath = _check_portname(name)
    return __salt__['cmd.run']('make rmconfig', cwd=portpath)


def showconfig(name, dict_return=False):
    '''
    Show the configuration options for a given port.

    CLI Example:

    .. code-block:: bash

        salt '*' ports.showconfig security/nmap
    '''
    portpath = _check_portname(name)

    try:
        result = __salt__['cmd.run_all']('make showconfig', cwd=portpath)
        output = result['stdout'].splitlines()
        if result['retcode'] != 0:
            error = result['stderr']
        else:
            error = ''
    except TypeError:
        error = result

    if error:
        msg = ('Error running \'make showconfig\' for {0}: {1}'
               .format(name, error))
        log.error(msg)
        raise SaltInvocationError(msg)

    if not dict_return:
        return '\n'.join(output)

    if ((not output) or ('configuration options' not in output[0])):
        return {}

    try:
        pkg = output[0].split()[-1].rstrip(':')
    except (IndexError, AttributeError, TypeError) as exc:
        log.error(
            'Unable to get pkg-version string: {0}'.format(exc)
        )
        return {}

    ret = {pkg: {}}
    output = output[1:]
    for line in output:
        try:
            opt, val, desc = re.match(
                r'\s+([^=]+)=(off|on): (.+)', line
            ).groups()
        except AttributeError:
            continue
        ret[pkg][opt] = val

    if not ret[pkg]:
        return {}
    return ret


def config(name, reset=False, **kwargs):
    '''
    Modify configuration options for a given port. Multiple options can be
    specified. To see the available options for a port, use
    :mod:`ports.showconfig <salt.modules.freebsdports.showconfig>`.

    name
        The port name, in ``category/name`` format

    reset : False
        If ``True``, runs a ``make rmconfig`` for the port, clearing its
        configuration before setting the desired options

    CLI Examples:

    .. code-block:: bash

        salt '*' ports.config security/nmap IPV6=off
    '''
    portpath = _check_portname(name)

    if reset:
        rmconfig(name)

    configuration = showconfig(name, dict_return=True)

    if not configuration:
        raise CommandExecutionError(
            'Unable to get port configuration for {0!r}'.format(name)
        )

    # Unpack return data from showconfig
    pkg = next(iter(configuration))
    configuration = configuration[pkg]

    def _on_off(val):
        '''
        Fix Salt's yaml-ification of on/off, and otherwise normalize the on/off
        values to be used in writing the options file
        '''
        if isinstance(val, bool):
            return 'on' if val else 'off'
        return str(val).lower()

    opts = dict(
        (x, _on_off(kwargs[x])) for x in kwargs if not x.startswith('_')
    )

    bad_opts = [x for x in opts if x not in configuration]
    if bad_opts:
        raise SaltInvocationError(
            'The following opts are not valid for port {0}: {1}'
            .format(name, ', '.join(bad_opts))
        )

    bad_vals = [
        '{0}={1}'.format(x, y) for x, y in opts.iteritems()
        if y not in ('on', 'off')
    ]
    if bad_vals:
        raise SaltInvocationError(
            'The following key/value pairs are invalid: {0}'
            .format(', '.join(bad_vals))
        )

    for opt, val in opts.iteritems():
        configuration[opt] = val

    _write_options(name, pkg, configuration)

    new_config = showconfig(name, dict_return=True)
    try:
        new_config = new_config[next(iter(new_config))]
    except (StopIteration, TypeError):
        return False

    return all(configuration[x] == new_config.get(x) for x in configuration)


def update(extract=False):
    '''
    Update the ports tree

    extract : False
        If ``True``, runs a ``portsnap extract`` after fetching, should be used
        for first-time installation of the ports tree.

    CLI Example:

    .. code-block:: bash

        salt '*' ports.update
    '''
    result = __salt__['cmd.run_all']('portsnap fetch')
    if not result['retcode'] == 0:
        raise CommandExecutionError(
            'Unable to fetch ports snapshot: {0}'.format(result['stderr'])
        )

    ret = []
    try:
        patch_count = re.search(
            r'Fetching (\d+) patches', result['stdout']
        ).group(1)
    except AttributeError:
        patch_count = 0

    try:
        new_port_count = re.search(
            r'Fetching (\d+) new ports or files', result['stdout']
        ).group(1)
    except AttributeError:
        new_port_count = 0

    ret.append('Applied {0} new patches'.format(patch_count))
    ret.append('Fetched {0} new ports or files'.format(new_port_count))

    if extract:
        result = __salt__['cmd.run_all']('portsnap extract')
        if not result['retcode'] == 0:
            raise CommandExecutionError(
                'Unable to extract ports snapshot {0}'.format(result['stderr'])
            )

    result = __salt__['cmd.run_all']('portsnap update')
    if not result['retcode'] == 0:
        raise CommandExecutionError(
            'Unable to apply ports snapshot: {0}'.format(result['stderr'])
        )

    return '\n'.join(ret)
