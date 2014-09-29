# -*- coding: utf-8 -*-
'''
Connection module for Amazon VPC

.. versionadded:: Helium

:configuration: This module accepts explicit autoscale credentials but can also
    utilize IAM roles assigned to the instance trough Instance Profiles.
    Dynamic credentials are then automatically obtained from AWS API and no
    further configuration is necessary. More Information available at::

       http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html

    If IAM roles are not used you need to specify them either in a pillar or
    in the minion's config file::

        asg.keyid: GKTADJGHEIQSXMKKRBJ08H
        asg.key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs

    A region may also be specified in the configuration::

        asg.region: us-east-1

    If a region is not specified, the default is us-east-1.

    It's also possible to specify key, keyid and region via a profile, either
    as a passed in dict, or as a string to pull from pillars or minion config:

        myprofile:
            keyid: GKTADJGHEIQSXMKKRBJ08H
            key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
            region: us-east-1

:depends: boto

'''

# Import Python libs
import logging
from distutils.version import LooseVersion as _LooseVersion

log = logging.getLogger(__name__)

# Import third party libs
try:
    import boto
    import boto.vpc

    logging.getLogger('boto').setLevel(logging.CRITICAL)
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False

from salt._compat import string_types


def __virtual__():
    '''
    Only load if boto libraries exist and if boto libraries are greater than
    a given version.
    '''
    required_boto_version = '2.8.0'
    # the boto_vpc execution module relies on the connect_to_region() method
    # which was added in boto 2.8.0
    # https://github.com/boto/boto/commit/33ac26b416fbb48a60602542b4ce15dcc7029f12
    if not HAS_BOTO:
        return False
    elif _LooseVersion(boto.__version__) < _LooseVersion(required_boto_version):
        return False
    else:
        return True


def get_subnet_association(subnets, region=None, key=None, keyid=None,
                           profile=None):
    '''
    Given a subnet (aka: a vpc zone identifier) or list of subnets, returns
    vpc association.

    Returns a VPC ID if the given subnets are associated with the same VPC ID.
    Returns False on an error or if the given subnets are associated with
    different VPC IDs.

    CLI Examples::

    .. code-block:: bash

        salt myminion boto_vpc.get_subnet_association subnet-61b47516

    .. code-block:: bash

        salt myminion boto_vpc.get_subnet_association ['subnet-61b47516','subnet-2cb9785b']

    '''
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False
    try:
        # subnet_ids=subnets can accept either a string or a list
        subnets = conn.get_all_subnets(subnet_ids=subnets)
    except boto.exception.BotoServerError as e:
        log.debug(e)
        return False
    # using a set to store vpc_ids - the use of set prevents duplicate
    # vpc_id values
    vpc_ids = set()
    for subnet in subnets:
        log.debug('examining subnet id: {0} for vpc_id'.format(subnet.id))
        if subnet in subnets:
            log.debug('subnet id: {0} is associated with vpc id: {1}'
                      .format(subnet.id, subnet.vpc_id))
            vpc_ids.add(subnet.vpc_id)
    if len(vpc_ids) == 1:
        vpc_id = vpc_ids.pop()
        log.info('all subnets are associated with vpc id: {0}'.format(vpc_id))
        return vpc_id
    else:
        log.info('given subnets are associated with fewer than 1 or greater'
                 ' than 1 subnets')
        return False


def exists(vpc_id, region=None, key=None, keyid=None, profile=None):
    '''
    Given a VPC ID, check to see if the given VPC ID exists.

    Returns True if the given VPC ID exists and returns False if the given
    VPC ID does not exist.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.exists myvpc

    '''
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False
    try:
        conn.get_all_vpcs(vpc_ids=[vpc_id])
        return True
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create(cidr_block, instance_tenancy=None, vpc_name=None, tags=None, region=None, key=None, keyid=None,
           profile=None):
    '''
    Given a valid CIDR block, create a VPC.

    An optional instance_tenancy argument can be provided. If provided, the valid values are 'default' or 'dedicated'
    An optional vpc_name argument can be provided.

    Returns True if the VPC was created and returns False if the VPC was not created.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.create '10.0.0.0/24'

    '''

    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        vpc = conn.create_vpc(cidr_block, instance_tenancy=instance_tenancy)
        if vpc:
            log.info('The newly created VPC id is {0}'.format(vpc.id))

            _maybe_set_name_tag(vpc_name, vpc)
            _maybe_set_tags(tags, vpc)

            return True
        else:
            log.warning('VPC was not created')
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def delete(vpc_id, region=None, key=None, keyid=None, profile=None):
    '''
    Given a VPC ID, delete the VPC.

    Returns True if the VPC was deleted and returns False if the VPC was not deleted.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.delete 'vpc-6b1fe402'

    '''

    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.delete_vpc(vpc_id):
            log.info('VPC {0} was deleted.'.format(vpc_id))

            return True
        else:
            log.warning('VPC {0} was not deleted.'.format(vpc_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_subnet(vpc_id, cidr_block, availability_zone=None, subnet_name=None, tags=None, region=None, key=None,
                  keyid=None, profile=None):
    '''
    Given a valid VPC ID and a CIDR block, create a subnet for the VPC.

    An optional availability zone argument can be provided.

    Returns True if the VPC subnet was created and returns False if the VPC subnet was not created.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.create_subnet 'vpc-6b1fe402' '10.0.0.0/25'

    '''

    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        vpc_subnet = conn.create_subnet(vpc_id, cidr_block, availability_zone=availability_zone)
        if vpc_subnet:
            log.info('A VPC subnet {0} with {1} available ips on VPC {2}'.format(vpc_subnet.id,
                                                                                 vpc_subnet.available_ip_address_count,
                                                                                 vpc_id))

            _maybe_set_name_tag(subnet_name, vpc_subnet)
            _maybe_set_tags(tags, vpc_subnet)

            return True
        else:
            log.warning('A VPC subnet was not created.')
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def delete_subnet(subnet_id, region=None, key=None, keyid=None, profile=None):
    '''
    Given a subnet ID, delete the subnet.

    Returns True if the subnet was deleted and returns False if the subnet was not deleted.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.delete_subnet 'subnet-6a1fe403'

    '''

    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.delete_subnet(subnet_id):
            log.debug('Subnet {0} was deleted.'.format(subnet_id))

            return True
        else:
            log.debug('Subnet {0} was not deleted.'.format(subnet_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def subnet_exists(subnet_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.get_all_subnets(subnet_ids=[subnet_id]):
            log.info('Subnet {0} exists.'.format(subnet_id))

            return True
        else:
            log.warning('Subnet {0} does not exist.'.format(subnet_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_customer_gateway(vpn_connection_type, ip_address, bgp_asn, customer_gateway_name=None, tags=None,
                            region=None, key=None, keyid=None, profile=None):
    '''
    Given a valid VPN connection type, a static IP address and a customer gateway’s Border Gateway Protocol (BGP) Autonomous System Number, create a customer gateway.

    Returns True if the customer gateway was created and returns False if the customer gateway was not created.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.create_customer_gateway 'ipsec.1', '12.1.2.3', 65534

    '''

    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        customer_gateway = conn.create_customer_gateway(vpn_connection_type, ip_address, bgp_asn)
        if customer_gateway:
            log.info('A customer gateway with id {0} was created'.format(customer_gateway.id))

            _maybe_set_name_tag(customer_gateway_name, customer_gateway)
            _maybe_set_tags(tags, customer_gateway)

            return True
        else:
            log.warning('A customer gateway was not created')
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def delete_customer_gateway(customer_gateway_id, region=None, key=None, keyid=None, profile=None):
    '''
    Given a customer gateway ID, delete the customer gateway.

    Returns True if the customer gateway was deleted and returns False if the customer gateway was not deleted.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.delete_customer_gateway 'cgw-b6a247df'

    '''

    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.delete_customer_gateway(customer_gateway_id):
            log.info('Customer gateway {0} was deleted.'.format(customer_gateway_id))

            return True
        else:
            log.warning('Customer gateway {0} was not deleted.'.format(customer_gateway_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def customer_gateway_exists(customer_gateway_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.get_all_customer_gateways(customer_gateway_ids=[customer_gateway_id]):
            log.info('Customer gateway {0} exists.'.format(customer_gateway_id))

            return True
        else:
            log.warning('Customer gateway {0} does not exist.'.format(customer_gateway_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_dhcp_options(domain_name=None, domain_name_servers=None, ntp_servers=None,
                        netbios_name_servers=None, netbios_node_type=None, dhcp_options_name=None, tags=None,
                        region=None, key=None, keyid=None, profile=None):
    '''
    Given valid DHCP options, create a DHCP options record.

    Returns True if the DHCP options record was created and returns False if the DHCP options record was not deleted.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.create_dhcp_options domain_name='example.com' domain_name_servers='[1.2.3.4]' ntp_servers='[5.6.7.8]' netbios_name_servers='[10.0.0.1]' netbios_node_type=1

    '''
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        dhcp_options = _create_dhcp_options(conn, domain_name=domain_name, domain_name_servers=domain_name_servers,
                                            ntp_servers=ntp_servers, netbios_name_servers=netbios_name_servers,
                                            netbios_node_type=netbios_node_type)
        if dhcp_options:
            log.info('DHCP options with id {0} were created'.format(dhcp_options.id))

            _maybe_set_name_tag(dhcp_options_name, dhcp_options)
            _maybe_set_tags(tags, dhcp_options)

            return True
        else:
            log.warning('DHCP options with id {0} were not created'.format(dhcp_options.id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def associate_dhcp_options_to_vpc(dhcp_options_id, vpc_id, region=None, key=None, keyid=None, profile=None):
    '''
    Given valid DHCP options id and a valid VPC id, associate the DHCP options record with the VPC.

    Returns True if the DHCP options record were associated and returns False if the DHCP options record was not associated.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.associate_dhcp_options_to_vpc 'dhcp-a0bl34pp' 'vpc-6b1fe402'

    '''
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False
    try:
        if conn.associate_dhcp_options(dhcp_options_id, vpc_id):
            log.info('DHCP options with id {0} were associated with VPC {1}'.format(dhcp_options_id, vpc_id))

            return True
        else:
            log.warning('DHCP options with id {0} were not associated with VPC {1}'.format(dhcp_options_id, vpc_id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def associate_new_dhcp_options_to_vpc(vpc_id, domain_name=None, domain_name_servers=None, ntp_servers=None,
                                      netbios_name_servers=None, netbios_node_type=None,
                                      region=None, key=None, keyid=None, profile=None):
    '''
    Given valid DHCP options and a valid VPC id, create and associate the DHCP options record with the VPC.

    Returns True if the DHCP options record were created and associated and returns False if the DHCP options record was not created and associated.

    CLI example::

    .. code-block:: bash

        salt myminion boto_vpc.associate_new_dhcp_options_to_vpc 'vpc-6b1fe402' domain_name='example.com' domain_name_servers='[1.2.3.4]' ntp_servers='[5.6.7.8]' netbios_name_servers='[10.0.0.1]' netbios_node_type=1

    '''
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False
    try:
        dhcp_options = _create_dhcp_options(conn, domain_name=domain_name, domain_name_servers=domain_name_servers,
                                            ntp_servers=ntp_servers, netbios_name_servers=netbios_name_servers,
                                            netbios_node_type=netbios_node_type)
        conn.associate_dhcp_options(dhcp_options.id, vpc_id)
        log.info('DHCP options with id {0} were created and associated with VPC {1}'.format(dhcp_options.id, vpc_id))
        return True
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def dhcp_options_exists(dhcp_options_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.get_all_dhcp_options(dhcp_options_ids=[dhcp_options_id]):
            log.info('DHCP options {0} exists.'.format(dhcp_options_id))

            return True
        else:
            log.warning('DHCP options {0} does not exist.'.format(dhcp_options_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_network_acl(vpc_id, network_acl_name=None, tags=None, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        network_acl = conn.create_network_acl(vpc_id)
        if network_acl:
            log.info('Network ACL with id {0} was created'.format(network_acl.id))
            _maybe_set_name_tag(network_acl_name, network_acl)
            _maybe_set_tags(tags, network_acl)
            return True
        else:
            log.warning('Network ACL was not created')
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def delete_network_acl(network_acl_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.delete_network_acl(network_acl_id):
            log.info('Network ACL with id {0} was deleted'.format(network_acl_id))
            return True
        else:
            log.warning('Network ACL with id {0} was not deleted'.format(network_acl_id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def network_acl_exists(network_acl_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.get_all_network_acls(network_acl_ids=[network_acl_id]):
            log.info('Network ACL with id {0} exists.'.format(network_acl_id))
            return True
        else:
            log.warning('Network ACL with id {0} does not exists.'.format(network_acl_id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def associate_network_acl_to_subnet(network_acl_id, subnet_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False
    try:
        if conn.associate_network_acl(network_acl_id, subnet_id):
            log.info('Network ACL with id {0} was associated with subnet {1}'.format(network_acl_id, subnet_id))

            return True
        else:
            log.warning('Network ACL with id {0} was not associated with subnet {1}'.format(network_acl_id, subnet_id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def associate_new_network_acl_to_subnet(vpc_id, subnet_id, network_acl_name=None, tags=None,
                                        region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False
    try:
        network_acl = conn.create_network_acl(vpc_id)
        if network_acl:
            log.info('Network ACL with id {0} was created'.format(network_acl.id))
            _maybe_set_name_tag(network_acl_name, network_acl)
            _maybe_set_tags(tags, network_acl)
        else:
            log.warning('Network ACL was not created')
            return False

        if conn.associate_network_acl(network_acl.id, subnet_id):
            log.info('Network ACL with id {0} was associated with subnet {1}'.format(network_acl.id, subnet_id))

            return True
        else:
            log.warning('Network ACL with id {0} was not associated with subnet {1}'.format(network_acl.id, subnet_id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def disassociate_network_acl(subnet_id, vpc_id=None, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        return conn.disassociate_network_acl(subnet_id, vpc_id=vpc_id)
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_network_acl_entry(network_acl_id, rule_number, protocol, rule_action, cidr_block, egress=None,
                             icmp_code=None, icmp_type=None, port_range_from=None, port_range_to=None,
                             region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        network_acl_entry = conn.create_network_acl_entry(network_acl_id, rule_number, protocol, rule_action,
                                                          cidr_block,
                                                          egress=egress, icmp_code=icmp_code, icmp_type=icmp_type,
                                                          port_range_from=port_range_from, port_range_to=port_range_to)
        if network_acl_entry:
            log.info('Network ACL entry was created')
            return True
        else:
            log.warning('Network ACL entry was not created')
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def replace_network_acl_entry(network_acl_id, rule_number, protocol, rule_action, cidr_block, egress=None,
                              icmp_code=None, icmp_type=None, port_range_from=None, port_range_to=None,
                              region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        network_acl_entry = conn.replace_network_acl_entry(network_acl_id, rule_number, protocol, rule_action,
                                                           cidr_block,
                                                           egress=egress,
                                                           icmp_code=icmp_code, icmp_type=icmp_type,
                                                           port_range_from=port_range_from, port_range_to=port_range_to)
        if network_acl_entry:
            log.info('Network ACL entry was replaced')
            return True
        else:
            log.warning('Network ACL entry was not replaced')
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def delete_network_acl_entry(network_acl_id, rule_number, egress=None, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        network_acl_entry = conn.delete_network_acl_entry(network_acl_id, rule_number, egress=egress)
        if network_acl_entry:
            log.info('Network ACL entry was deleted')
            return True
        else:
            log.warning('Network ACL was not deleted')
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_route_table(vpc_id, route_table_name=None, tags=None, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        route_table = conn.create_route_table(vpc_id)
        if route_table:
            log.info('Route table with id {0} was created'.format(route_table.id))
            _maybe_set_name_tag(route_table_name, route_table)
            _maybe_set_tags(tags, route_table)
            return True
        else:
            log.warning('Route table ACL was not created')
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def delete_route_table(route_table_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.delete_route_table(route_table_id):
            log.info('Route table with id {0} was deleted'.format(route_table_id))
            return True
        else:
            log.warning('Route table with id {0} was not deleted'.format(route_table_id))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def route_table_exists(route_table_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.get_all_route_tables(route_table_ids=[route_table_id]):
            log.info('Route table {0} exists.'.format(route_table_id))

            return True
        else:
            log.warning('Route table {0} does not exist.'.format(route_table_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def associate_route_table(route_table_id, subnet_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        association_id = conn.associate_route_table(route_table_id, subnet_id)
        log.info('Route table {0} was associated with subnet {1}'.format(route_table_id, subnet_id))

        return association_id
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def disassociate_route_table(association_id, region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.disassociate_route_table(association_id):
            log.info('Route table with association id {0} has been disassociated.'.format(association_id))

            return True
        else:
            log.warning('Route table with association id {0} has not been disassociated.'.format(association_id))

            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def create_route(route_table_id, destination_cidr_block, gateway_id=None, instance_id=None, interface_id=None,
                 region=None, key=None, keyid=None, profile=None):
    conn = _get_conn(region, key, keyid, profile)
    if not conn:
        return False

    try:
        if conn.create_route(route_table_id, destination_cidr_block, gateway_id=gateway_id, instance_id=instance_id,
                             interface_id=interface_id):
            log.info('Route with cider block {0} on route table {1} was created'.format(route_table_id,
                                                                                        destination_cidr_block))

            return True
        else:
            log.warning('Route with cider block {0} on route table {1} was not created'.format(route_table_id,
                                                                                               destination_cidr_block))
            return False
    except boto.exception.BotoServerError as e:
        log.error(e)
        return False


def _get_conn(region, key, keyid, profile):
    '''
    Get a boto connection to vpc.
    '''
    if profile:
        if isinstance(profile, string_types):
            _profile = __salt__['config.option'](profile)
        elif isinstance(profile, dict):
            _profile = profile
        key = _profile.get('key', None)
        keyid = _profile.get('keyid', None)
        region = _profile.get('region', None)

    if not region and __salt__['config.option']('vpc.region'):
        region = __salt__['config.option']('vpc.region')

    if not region:
        region = 'us-east-1'

    if not key and __salt__['config.option']('vpc.key'):
        key = __salt__['config.option']('vpc.key')
    if not keyid and __salt__['config.option']('vpc.keyid'):
        keyid = __salt__['config.option']('vpc.keyid')

    try:
        conn = boto.vpc.connect_to_region(region, aws_access_key_id=keyid,
                                          aws_secret_access_key=key)
    except boto.exception.NoAuthHandlerFound:
        log.error('No authentication credentials found when attempting to'
                  ' make boto autoscale connection.')
        return None
    return conn


def _create_dhcp_options(conn, domain_name=None, domain_name_servers=None, ntp_servers=None, netbios_name_servers=None,
                         netbios_node_type=None):
    return conn.create_dhcp_options(domain_name=domain_name, domain_name_servers=domain_name_servers,
                                    ntp_servers=ntp_servers, netbios_name_servers=netbios_name_servers,
                                    netbios_node_type=netbios_node_type)


def _maybe_set_name_tag(name, obj):
    if name:
        obj.add_tag("Name", name)

        log.debug('{0} is now named as {1}'.format(obj, name))


def _maybe_set_tags(tags, obj):
    if tags:
        obj.add_tags(tags)

        log.debug('The following tags: {0} were added to {1}'.format(', '.join(tags), obj))