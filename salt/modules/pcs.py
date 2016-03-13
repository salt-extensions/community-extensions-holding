# -*- coding: utf-8 -*-
'''
Pcs Command Wrapper
========================

The pcs command is wrapped for specific functions

:depends: pcs
'''
from __future__ import absolute_import

# Import python libs
import os

# Import salt libs
import salt.utils


def __virtual__():
    '''
    Only load if pcs is installed
    '''
    if salt.utils.which('pcs'):
        return 'pcs'
    return False


def auth(nodes, pcsuser='hacluster', pcspasswd='hacluster', extra_args = []):
    '''
    Authorize nodes

    CLI Example:

    .. code-block:: bash

        salt '*' pcs.auth nodes='[ node1.example.org node2.example.org ]' \\
                          pcsuser='hacluster' \\
                          pcspasswd='hacluster' \\
                          extra_args=[ '--force' ]
    '''
    cmd = [ 'pcs',  'cluster',  'auth'  ]

    if pcsuser:
      cmd +=  [ '-u', pcsuser ]

    if pcspasswd:
      cmd +=  [ '-p',  pcspasswd ]

    cmd += extra_args
    cmd += nodes

    return __salt__['cmd.run_all'](cmd, output_loglevel='trace', python_shell=False)

def is_auth(nodes):
    '''
    Check if nodes are already authorized

    CLI Example:

    .. code-block:: bash

        salt '*' pcs.is_auth nodes='[ node1.example.org node2.example.org ]' 
    '''
    cmd = [ 'pcs',  'cluster',  'auth'  ]
    cmd += nodes

    return __salt__['cmd.run_all'](cmd, stdin='\n\n', output_loglevel='trace', python_shell=False)

def cluster_setup(nodes, pcsclustername='pcscluster', extra_args = []):
    '''
    Setup pacemaker cluster via pcs

    CLI Example:

    .. code-block:: bash

        salt '*' pcs.cluster_setup nodes='[ node1.example.org node2.example.org ]' \\
                                   pcsclustername='pcscluster', \\
                                   extra_args=[ '' ]
    '''
    cmd = [ 'pcs',  'cluster',  'setup'  ]

    cmd += [ '--name', pcsclustername ]

    cmd += nodes
    cmd += extra_args

    return __salt__['cmd.run_all'](cmd, output_loglevel='trace', python_shell=False)

def config_show():
    '''
    Show config of cluster

    CLI Example:

    .. code-block:: bash

        salt '*' pcs.config_show 
    '''
    cmd = [ 'pcs',  'config',  'show'  ]

    return __salt__['cmd.run_all'](cmd, output_loglevel='trace', python_shell=False)

def cluster_node_add(node, extra_args = []):
    '''
    Add a node to the pacemaker cluster via pcs

    CLI Example:

    .. code-block:: bash

        salt '*' pcs.cluster_node_add node=node2.example.org' \\
                                      extra_args=[ '' ]
    '''
    cmd = [ 'pcs',  'cluster',  'node', 'add'  ]

    cmd += [ node ]
    cmd += extra_args

    return __salt__['cmd.run_all'](cmd, output_loglevel='trace', python_shell=False)

def stonith_create(stonith_id, stonith_device_type, stonith_device_options = []):
    '''
    Create a stonith resource via pcs

    CLI Example:

    .. code-block:: bash

        salt '*' pcs.stonith_create stonith_id='my_fence_eps' \\
                                    stonith_device_type='fence_eps' \\
                                    stonith_device_options="[ \\
                                      'pcmk_host_map=\\"node1.example.org:01;node2.example.org:02\\"', \\
                                      'ipaddr=\\"myepsdevice.example.org\\"', \\
                                      'action=\\"reboot\\"', \\
                                      'power_wait=\\"5\\"', \\
                                      'verbose=\\"1\\"', \\
                                      'debug=\\"/var/log/pcsd/my_fence_eps.log\\"', \\
                                      'login=\\"hidden\\"', \\
                                      'passwd=\\"hoonetorg\\"' \\
                                    ]"
    '''
    cmd = [ 'pcs',  'stonith',  'create',  stonith_id, stonith_device_type ] + stonith_device_options

    return __salt__['cmd.run_all'](cmd, output_loglevel='trace', python_shell=False)
