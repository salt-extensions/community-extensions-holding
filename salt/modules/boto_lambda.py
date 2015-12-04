# -*- coding: utf-8 -*-
'''
Connection module for Amazon Lambda

.. versionadded:: 

:configuration: This module accepts explicit Lambda credentials but can also
    utilize IAM roles assigned to the instance trough Instance Profiles.
    Dynamic credentials are then automatically obtained from AWS API and no
    further configuration is necessary. More Information available at:

    .. code-block:: text

        http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html

    If IAM roles are not used you need to specify them either in a pillar or
    in the minion's config file:

    .. code-block:: yaml

        lambda.keyid: GKTADJGHEIQSXMKKRBJ08H
        lambda.key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs

    A region may also be specified in the configuration:

    .. code-block:: yaml

        lambda.region: us-east-1

    If a region is not specified, the default is us-east-1.

    It's also possible to specify key, keyid and region via a profile, either
    as a passed in dict, or as a string to pull from pillars or minion config:

    .. code-block:: yaml

        myprofile:
            keyid: GKTADJGHEIQSXMKKRBJ08H
            key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
            region: us-east-1

.. versionchanged:: 2015.8.0
    All methods now return a dictionary. Create and delete methods return:

    .. code-block:: yaml

        created: true

    or

    .. code-block:: yaml

        created: false
        error:
          message: error message

    Request methods (e.g., `describe_function`) return:

    .. code-block:: yaml

        function:
          - {...}
          - {...}

    or

    .. code-block:: yaml

        error:
          message: error message

:depends: boto3

'''
# keep lint from choking on _get_conn and _cache_id
#pylint: disable=E0602

# Import Python libs
from __future__ import absolute_import
import logging
import socket
from distutils.version import LooseVersion as _LooseVersion  # pylint: disable=import-error,no-name-in-module

# Import Salt libs
import salt.utils.boto3
import salt.utils.compat
from salt.exceptions import SaltInvocationError, CommandExecutionError
# from salt.utils import exactly_one
# TODO: Uncomment this and s/_exactly_one/exactly_one/
# See note in utils.boto

log = logging.getLogger(__name__)

# Import third party libs
import salt.ext.six as six
# pylint: disable=import-error
try:
    #pylint: disable=unused-import
    import boto
    import boto3
    #pylint: enable=unused-import
    from botocore.exceptions import ClientError
    logging.getLogger('boto').setLevel(logging.CRITICAL)
    logging.getLogger('boto3').setLevel(logging.CRITICAL)
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False
# pylint: enable=import-error


def __virtual__():
    '''
    Only load if boto libraries exist and if boto libraries are greater than
    a given version.
    '''
    required_boto_version = '2.8.0'
    required_boto3_version = '1.2.1'
    # the boto_lambda execution module relies on the connect_to_region() method
    # which was added in boto 2.8.0
    # https://github.com/boto/boto/commit/33ac26b416fbb48a60602542b4ce15dcc7029f12
    if not HAS_BOTO:
        return False
    elif _LooseVersion(boto.__version__) < _LooseVersion(required_boto_version):
        return False
    elif _LooseVersion(boto3.__version__) < _LooseVersion(required_boto3_version):
        return False
    else:
        return True


def __init__(opts):
    salt.utils.compat.pack_dunder(__name__)
    if HAS_BOTO:
        __utils__['boto3.assign_funcs'](__name__, 'lambda')

def _multi_call(function, *args, **kwargs):
    """Retrieve full set of values from a boto3 API call that may truncate
    its results
    """
    ret = function(*args, **kwargs)
    # determine the non-marker key name
    all = ret.keys()
    if 'NextMarker' in all:
        all.remove('NextMarker')
    content = all[0]
    # handle a marker indicating the result was truncated
    marker = getattr(ret, 'NextMarker', None)
    while marker:
        more = function(*args, Marker=marker, **kwargs)
        ret[content].extend(more[content])
        marker = getattr(ret, 'NextMarker', None)
    return ret

def _find_function(name,
               region=None, key=None, keyid=None, profile=None):

    '''
    Given function name, find and return matching Lambda information.
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    funcs = _multi_call(conn.list_functions)

    for func in funcs['Functions']:
        if func['FunctionName'] == name:
            return func
    return None


def function_exists(FunctionName, region=None, key=None,
           keyid=None, profile=None):
    '''
    Given a function name, check to see if the given function name exists.

    Returns True if the given function exists and returns False if the given
    function does not exist.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.function_exists myfunction

    '''

    try:
        func = _find_function(FunctionName,
                             region=region, key=key, keyid=keyid, profile=profile)
        return {'exists': bool(func)}
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def _get_role_arn(name, region=None, key=None, keyid=None, profile=None):
    if name.startswith('arn:aws:iam:'):
        return name

    account_id = __salt__['boto_iam.get_account_id'](
        region=region, key=key, keyid=keyid, profile=profile
    )
    return 'arn:aws:iam::{0}:role/{1}'.format(account_id, name)


def _filedata(infile):
    with open(infile, 'rb') as f:
       return f.read()

def create_function(FunctionName, Runtime, Role, Handler, ZipFile=None,
                    S3Bucket=None, S3Key=None, S3ObjectVersion=None,
                    Description="", Timeout=3, MemorySize=128, Publish=False,
            region=None, key=None, keyid=None, profile=None):
    '''
    Given a valid config, create a function.

    Returns {created: true} if the function was created and returns
    {created: False} if the function was not created.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.create_function my_function python2.7 my_role my_file.my_function my_function.zip

    '''

    role_arn = _get_role_arn(Role, region=region, key=key, keyid=keyid, profile=profile)
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        if ZipFile:
            if S3Bucket or S3Key or S3ObjectVersion:
                raise SaltInvocationError('Either ZipFile must be specified, or '
                                'S3Bucket and S3Key must be provided.')
            code = {
               'ZipFile': _filedata(ZipFile),
            }
        else:
            code = {
               'S3Bucket': S3Bucket,
               'S3Key': S3Key,
            }
            if S3ObjectVersion:
                code['S3ObjectVersion']= S3ObjectVersion
        func = conn.create_function(FunctionName=FunctionName, Runtime=Runtime, Role=role_arn, Handler=Handler, 
                                   Code=code, Description=Description, Timeout=Timeout, MemorySize=MemorySize, 
                                   Publish=Publish)
        if func:
            log.info('The newly created function name is {0}'.format(func['FunctionName']))

            return {'created': True, 'name': func['FunctionName']}
        else:
            log.warning('Function was not created')
            return {'created': False}
    except ClientError as e:
        return {'created': False, 'error': salt.utils.boto3.get_error(e)}


def delete_function(FunctionName, Qualifier=None, region=None, key=None, keyid=None, profile=None):
    '''
    Given a function name and optional version qualifier, delete it.

    Returns {deleted: true} if the function was deleted and returns
    {deleted: false} if the function was not deleted.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.delete_function myfunction

    '''

    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        if Qualifier:
           conn.delete_function(FunctionName=FunctionName, Qualifier=Qualifier)
        else:
           conn.delete_function(FunctionName=FunctionName)
        return {'deleted': True}
    except ClientError as e:
        return {'deleted': False, 'error': salt.utils.boto3.get_error(e)}


def describe_function(FunctionName, region=None, key=None,
             keyid=None, profile=None):
    '''
    Given a function name describe its properties.

    Returns a dictionary of interesting properties.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.describe_function myfunction

    '''

    try:
        func = _find_function(FunctionName,
                             region=region, key=key, keyid=keyid, profile=profile)
        if func:
            keys = ('FunctionName', 'Runtime', 'Role', 'Handler', 'CodeSha256',
                'CodeSize', 'Description', 'Timeout', 'MemorySize', 'FunctionArn',
                'LastModified')
            return {'function': dict([(k, func.get(k)) for k in keys])}
        else:
            return {'function': None}
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def update_function_config(FunctionName, Role, Handler, Description="", Timeout=3, MemorySize=128,
            region=None, key=None, keyid=None, profile=None):
    '''
    Update the named lambda function to the configuration.

    Returns {updated: true} if the function was updated and returns
    {updated: False} if the function was not updated.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.update_function_config my_function my_role my_file.my_function "my lambda function"

    '''

    role_arn = _get_role_arn(Role, region, key, keyid, profile)
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        r = conn.update_function_configuration(FunctionName=FunctionName,
                                               Role=role_arn, Handler=Handler, 
                                               Description=Description, Timeout=Timeout,
                                               MemorySize=MemorySize)
        if r:
            keys = ('FunctionName', 'Runtime', 'Role', 'Handler', 'CodeSha256',
                'CodeSize', 'Description', 'Timeout', 'MemorySize', 'FunctionArn',
                'LastModified')
            return {'updated': True, 'function': dict([(k, r.get(k)) for k in keys])}
        else:
            log.warning('Function was not updated')
            return {'updated': False}
    except ClientError as e:
        return {'updated': False, 'error': salt.utils.boto3.get_error(e)}


def update_function_code(FunctionName, ZipFile=None, S3Bucket=None, S3Key=None,
            S3ObjectVersion=None, Publish=False,
            region=None, key=None, keyid=None, profile=None):
    '''
    Upload the given code to the named lambda function.

    Returns {updated: true} if the function was updated and returns
    {updated: False} if the function was not updated.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.update_function_code my_function ZipFile=function.zip

    '''

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    try:
        if ZipFile:
            if S3Bucket or S3Key or S3ObjectVersion:
                raise SaltInvocationError('Either ZipFile must be specified, or '
                                'S3Bucket and S3Key must be provided.')
            r = conn.update_function_code(FunctionName=FunctionName,
                                   ZipFile=_filedata(ZipFile),
                                   Publish=Publish)
        else:
            args = {
                'S3Bucket': S3Bucket, 
                'S3Key': S3Key,
            }
            if S3ObjectVersion:
              args['S3ObjectVersion'] = S3ObjectVersion
            r = conn.update_function_code(FunctionName=FunctionName,
                                   Publish=Publish, **args)
        if r:
            keys = ('FunctionName', 'Runtime', 'Role', 'Handler', 'CodeSha256',
                'CodeSize', 'Description', 'Timeout', 'MemorySize', 'FunctionArn',
                'LastModified')
            return {'updated': True, 'function': dict([(k, r.get(k)) for k in keys])}
        else:
            log.warning('Function was not updated')
            return {'updated': False}
    except ClientError as e:
        return {'created': False, 'error': salt.utils.boto3.get_error(e)}


def list_function_versions(FunctionName, 
            region=None, key=None, keyid=None, profile=None):
    '''
    List the versions available for the given function.

    Returns {created: true} if the alias was created and returns
    {created: False} if the alias was not created.

    CLI Example:

    .. code-block:: yaml

        versions:
          - {...}
          - {...}

    '''
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        vers = _multi_call(con.list_versions_by_function, 
                                 FunctionName=FunctionName)
        if vers:
            return vers
        else:
            log.warning('No versions found')
            return { 'Versions': [] }
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def create_alias(FunctionName, Name, FunctionVersion, Description="",
            region=None, key=None, keyid=None, profile=None):
    '''
    Given a valid config, create an alias to a function.

    Returns {created: true} if the alias was created and returns
    {created: False} if the alias was not created.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.create_alias my_function my_alias $LATEST "An alias"

    '''
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        alias = conn.create_alias(FunctionName=FunctionName, Name=Name,
                                   FunctionVersion=FunctionVersion, Description=Description)
        if alias:
            log.info('The newly created alias name is {0}'.format(alias['Name']))

            return {'created': True, 'name': alias['Name']}
        else:
            log.warning('Alias was not created')
            return {'created': False}
    except ClientError as e:
        return {'created': False, 'error': salt.utils.boto3.get_error(e)}


def delete_alias(FunctionName, Name, region=None, key=None, keyid=None, profile=None):
    '''
    Given a function name and alias name, delete the alias.

    Returns {deleted: true} if the alias was deleted and returns
    {deleted: false} if the alias was not deleted.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.delete_alias myfunction myalias

    '''

    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        conn.delete_alias(FunctionName=FunctionName, Name=Name)
        return {'deleted': True}
    except ClientError as e:
        return {'deleted': False, 'error': salt.utils.boto3.get_error(e)}


def _find_alias(FunctionName, Name, FunctionVersion=None,
               region=None, key=None, keyid=None, profile=None):

    '''
    Given function name and alias name, find and return matching alias information.
    '''
    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)

    if FunctionVersion:
        aliases = _multi_call(conn.list_aliases, FunctionName=FunctionName,
                        FunctionVersion=FunctionVersion)
    else:
        aliases = _multi_call(conn.list_aliases, FunctionName=FunctionName)

    for alias in aliases.get('Aliases'):
        if alias['Name'] == Name:
           return alias
    return None


def alias_exists(FunctionName, Name, region=None, key=None,
           keyid=None, profile=None):
    '''
    Given a function name and alias name, check to see if the given alias exists.

    Returns True if the given alias exists and returns False if the given
    alias does not exist.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.alias_exists myfunction myalias

    '''

    try:
        alias = _find_alias(FunctionName, Name,
                             region=region, key=key, keyid=keyid, profile=profile)
        return {'exists': bool(alias)}
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def describe_alias(FunctionName, Name, region=None, key=None,
             keyid=None, profile=None):
    '''
    Given a function name and alias name describe the properties of the alias.

    Returns a dictionary of interesting properties.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.describe_alias myalias

    '''

    try:
        alias = _find_alias(FunctionName, Name,
                             region=region, key=key, keyid=keyid, profile=profile)
        if alias:
            keys = ('Name', 'FunctionVersion', 'Description')
            return {'alias': dict([(k, alias.get(k)) for k in keys])}
        else:
            return {'alias': None}
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def update_alias(FunctionName, Name, FunctionVersion=None, Description=None,
            region=None, key=None, keyid=None, profile=None):
    '''
    Update the named alias to the configuration.

    Returns {updated: true} if the alias was updated and returns
    {updated: False} if the alias was not updated.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.update_alias my_lambda my_alias $LATEST

    '''

    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        args= {}
        if FunctionVersion:
            args['FunctionVersion'] = FunctionVersion
        if Description:
            args['Description'] = Description
        r = conn.update_alias(FunctionName=FunctionName, Name=Name, **args)
        if r:
            keys = ('Name', 'FunctionVersion', 'Description')
            return {'updated': True, 'alias': dict([(k, r.get(k)) for k in keys])}
        else:
            log.warning('Alias was not updated')
            return {'updated': False}
    except ClientError as e:
        return {'created': False, 'error': salt.utils.boto3.get_error(e)}


def create_event_source_mapping(EventSourceArn, FunctionName, StartingPosition,
            Enabled=True, BatchSize=100, 
            region=None, key=None, keyid=None, profile=None):
    '''
    Identifies a stream as an event source for a Lambda function. It can be
    either an Amazon Kinesis stream or an Amazon DynamoDB stream. AWS Lambda
    invokes the specified function when records are posted to the stream.

    Returns {created: true} if the event source mapping was created and returns
    {created: False} if the event source mapping was not created.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.create_event_source_mapping arn::::eventsource myfunction LATEST

    '''
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        obj = conn.create_event_source_mapping(EventSourceArn=EventSourceArn,
                                               FunctionName=FunctionName,
                                               Enabled=Enabled,
                                               BatchSize=BatchSize,
                                               StartingPosition=StartingPosition)
        if obj:
            log.info('The newly created event source mapping ID is {0}'.format(obj['UUID']))

            return {'created': True, 'id': obj['UUID']}
        else:
            log.warning('Event source mapping was not created')
            return {'created': False}
    except ClientError as e:
        return {'created': False, 'error': salt.utils.boto3.get_error(e)}


def get_event_source_mapping_ids(EventSourceArn, FunctionName, 
           region=None, key=None, keyid=None, profile=None):
    '''
    Given an event source and function name, return a list of mapping IDs

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.get_event_source_mapping_ids arn:::: myfunction

    '''

    conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
    try:
        maps = _multi_call(conn.list_event_source_mappings, 
                                               EventSourceArn=EventSourceArn,
                                               FunctionName=FunctionName)['EventSourceMappings']
        return [mapping['UUID'] for mapping in maps]
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def _get_ids(UUID=None, EventSourceArn=None, FunctionName=None,
                                region=None, key=None, keyid=None, profile=None):
    if UUID:
        if EventSourceArn or FunctionName:
            raise SaltInvocationError('Either UUID must be specified, or '
                                'EventSourceArn and FunctionName must be provided.')
        return [ UUID ]
    else:
        if not EventSourceArn or not FunctionName:
            raise SaltInvocationError('Either UUID must be specified, or '
                                'EventSourceArn and FunctionName must be provided.')
        return get_event_source_mapping_ids(EventSourceArn=EventSourceArn,
                                            FunctionName=FunctionName,
                       region=region, key=key, keyid=keyid, profile=profile)


def delete_event_source_mapping(UUID=None, EventSourceArn=None, FunctionName=None, 
                                region=None, key=None, keyid=None, profile=None):
    '''
    Given an event source mapping ID or an event source ARN and FunctionName,
    delete the event source mapping

    Returns {deleted: true} if the mapping was deleted and returns
    {deleted: false} if the mapping was not deleted.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.delete_event_source_mapping 260c423d-e8b5-4443-8d6a-5e91b9ecd0fa

    '''
    ids = _get_ids(UUID, EventSourceArn=EventSourceArn,
                         FunctionName=FunctionName)
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        for id in ids:
            conn.delete_event_source_mapping(UUID=id)
        return {'deleted': True}
    except ClientError as e:
        return {'deleted': False, 'error': salt.utils.boto3.get_error(e)}


def event_source_mapping_exists(UUID=None, EventSourceArn=None,
           FunctionName=None,
           region=None, key=None, keyid=None, profile=None):
    '''
    Given an event source mapping ID or an event source ARN and FunctionName,
    check whether the mapping exists.

    Returns True if the given alias exists and returns False if the given
    alias does not exist.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.alias_exists myfunction myalias

    '''

    desc = describe_event_source_mapping(UUID=UUID,
                                         EventSourceArn=EventSourceArn,
                                         FunctionName=FunctionName,
                                         region=region, key=key,
                                         keyid=keyid, profile=profile)
    return {'exists': bool(desc.get('event_source_mapping'))}


def describe_event_source_mapping(UUID=None, EventSourceArn=None,
           FunctionName=None,
           region=None, key=None, keyid=None, profile=None):
    '''
    Given an event source mapping ID or an event source ARN and FunctionName,
    obtain the current settings of that mapping.

    Returns a dictionary of interesting properties.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lambda.describe_event_source_mapping uuid

    '''

    ids = _get_ids(UUID, EventSourceArn=EventSourceArn,
                         FunctionName=FunctionName)
    if len(ids) < 1:
        return {'event_source_mapping': None}

    UUID = ids[0]
    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        desc = conn.get_event_source_mapping(UUID=UUID)
        if desc:
            keys = ('UUID', 'BatchSize', 'EventSourceArn',
                    'FunctionArn','LastModified','LastProcessingResult',
                    'State','StateTransitionReason')
            return {'event_source_mapping': dict([(k, desc.get(k)) for k in keys])}
        else:
            return {'event_source_mapping': None}
    except ClientError as e:
        return {'error': salt.utils.boto3.get_error(e)}


def update_event_source_mapping(UUID, 
            FunctionName=None, Enabled=None, BatchSize=None,
            region=None, key=None, keyid=None, profile=None):
    '''
    Update the event source mapping identified by the UUID.

    Returns {updated: true} if the alias was updated and returns
    {updated: False} if the alias was not updated.

    CLI Example:

    .. code-block:: bash

        salt myminion boto_lamba.update_event_source_mapping uuid FunctionName=new_function

    '''

    try:
        conn = _get_conn(region=region, key=key, keyid=keyid, profile=profile)
        args= {}
        if not FunctionName is None:
            args['FunctionName'] = FunctionName
        if not Enabled is None:
            args['Enabled'] = Enabled
        if not BatchSize is None:
            args['BatchSize'] = BatchSize
        r = conn.update_event_source_mapping(UUID=UUID, **args)
        if r:
            keys = ('UUID', 'BatchSize', 'EventSourceArn',
                    'FunctionArn', 'LastModified', 'LastProcessingResult',
                    'State', 'StateTransitionReason')
            return {'updated': True, 'event_source_mapping': dict([(k, r.get(k)) for k in keys])}
        else:
            log.warning('Mapping was not updated')
            return {'updated': False}
    except ClientError as e:
        return {'created': False, 'error': salt.utils.boto3.get_error(e)}
