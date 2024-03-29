"""
Management of Pacemaker/Corosync clusters with PCS
==================================================

A state module to manage Pacemaker/Corosync clusters
with the Pacemaker/Corosync configuration system (PCS)

.. versionadded:: 2016.11.0

:depends: pcs

Walkthrough of a complete PCS cluster setup:
http://clusterlabs.org/doc/en-US/Pacemaker/1.1/html/Clusters_from_Scratch/

Requirements:
    PCS is installed, pcs service is started and
    the password for the hacluster user is set and known.

Remark on the cibname variable used in the examples:
    The use of the cibname variable is optional.
    Use it only if you want to deploy your changes into a cibfile first and then push it.
    This makes only sense if you want to deploy multiple changes (which require each other) at once to the cluster.

At first the cibfile must be created:

.. code-block:: yaml

    mysql_pcs__cib_present_cib_for_galera:
        pcs.cib_present:
            - cibname: cib_for_galera
            - scope: None
            - extra_args: None

Then the cibfile can be modified by creating resources (creating only 1 resource for demonstration, see also 7.):

.. code-block:: yaml

    mysql_pcs__resource_present_galera:
        pcs.resource_present:
            - resource_id: galera
            - resource_type: "ocf:heartbeat:galera"
            - resource_options:
                - 'wsrep_cluster_address=gcomm://node1.example.org,node2.example.org,node3.example.org'
                - '--master'
            - cibname: cib_for_galera

After modifying the cibfile, it can be pushed to the live CIB in the cluster:

.. code-block:: yaml

    mysql_pcs__cib_pushed_cib_for_galera:
        pcs.cib_pushed:
            - cibname: cib_for_galera
            - scope: None
            - extra_args: None

Create a cluster from scratch:

1. This authorizes nodes to each other. It probably won't work with Ubuntu as
    it rolls out a default cluster that needs to be destroyed before the
    new cluster can be created. This is a little complicated so it's best
    to just run the cluster_setup below in most cases.:

   .. code-block:: yaml

       pcs_auth__auth:
           pcs.auth:
               - nodes:
                   - node1.example.com
                   - node2.example.com
               - pcsuser: hacluster
               - pcspasswd: hoonetorg


2. Do the initial cluster setup:

   .. code-block:: yaml

       pcs_setup__setup:
           pcs.cluster_setup:
               - nodes:
                   - node1.example.com
                   - node2.example.com
               - pcsclustername: pcscluster
               - extra_args:
                   - '--start'
                   - '--enable'
               - pcsuser: hacluster
               - pcspasswd: hoonetorg

3. Optional: Set cluster properties:

   .. code-block:: yaml

       pcs_properties__prop_has_value_no-quorum-policy:
           pcs.prop_has_value:
               - prop: no-quorum-policy
               - value: ignore
               - cibname: cib_for_cluster_settings

4. Optional: Set resource defaults:

   .. code-block:: yaml

       pcs_properties__resource_defaults_to_resource-stickiness:
           pcs.resource_defaults_to:
               - default: resource-stickiness
               - value: 100
               - cibname: cib_for_cluster_settings

5. Optional: Set resource op defaults:

   .. code-block:: yaml

       pcs_properties__resource_op_defaults_to_monitor-interval:
           pcs.resource_op_defaults_to:
               - op_default: monitor-interval
               - value: 60s
               - cibname: cib_for_cluster_settings

6. Configure Fencing (!is often not optional on production ready cluster!):

   .. code-block:: yaml

       pcs_stonith__created_eps_fence:
           pcs.stonith_present:
               - stonith_id: eps_fence
               - stonith_device_type: fence_eps
               - stonith_device_options:
                   - 'pcmk_host_map=node1.example.org:01;node2.example.org:02'
                   - 'ipaddr=myepsdevice.example.org'
                   - 'power_wait=5'
                   - 'verbose=1'
                   - 'debug=/var/log/pcsd/eps_fence.log'
                   - 'login=hidden'
                   - 'passwd=hoonetorg'
               - cibname: cib_for_stonith

7. Add resources to your cluster:

   .. code-block:: yaml

       mysql_pcs__resource_present_galera:
           pcs.resource_present:
               - resource_id: galera
               - resource_type: "ocf:heartbeat:galera"
               - resource_options:
                   - 'wsrep_cluster_address=gcomm://node1.example.org,node2.example.org,node3.example.org'
                    - '--master'
                - cibname: cib_for_galera

8. Optional: Add constraints (locations, colocations, orders):

   .. code-block:: yaml

       haproxy_pcs__constraint_present_colocation-vip_galera-haproxy-clone-INFINITY:
           pcs.constraint_present:
               - constraint_id: colocation-vip_galera-haproxy-clone-INFINITY
               - constraint_type: colocation
               - constraint_options:
                   - 'add'
                   - 'vip_galera'
                   - 'with'
                   - 'haproxy-clone'
               - cibname: cib_for_haproxy

.. versionadded:: 2016.3.0
"""

import logging
import os

import salt.utils.files
import salt.utils.path
import salt.utils.stringutils

log = logging.getLogger(__name__)


def __virtual__():
    """
    Only load if pcs package is installed
    """
    if salt.utils.path.which("pcs"):
        return "pcs"
    return (False, "Unable to locate command: pcs")


def _file_read(path):
    """
    Read a file and return content
    """
    content = False
    if os.path.exists(path):
        with salt.utils.files.fopen(path, "r+") as fp_:
            content = salt.utils.stringutils.to_unicode(fp_.read())
        fp_.close()
    return content


def _file_write(path, content):
    """
    Write content to a file
    """
    with salt.utils.files.fopen(path, "w+") as fp_:
        fp_.write(salt.utils.stringutils.to_str(content))
    fp_.close()


def _get_cibpath():
    """
    Get the path to the directory on the minion where CIB's are saved
    """
    cibpath = os.path.join(__opts__["cachedir"], "pcs", __env__)
    log.trace("cibpath: %s", cibpath)
    return cibpath


def _get_cibfile(cibname):
    """
    Get the full path of a cached CIB-file with the name of the CIB
    """
    cibfile = os.path.join(_get_cibpath(), "{}.{}".format(cibname, "cib"))
    log.trace("cibfile: %s", cibfile)
    return cibfile


def _get_cibfile_tmp(cibname):
    """
    Get the full path of a temporary CIB-file with the name of the CIB
    """
    cibfile_tmp = f"{_get_cibfile(cibname)}.tmp"
    log.trace("cibfile_tmp: %s", cibfile_tmp)
    return cibfile_tmp


def _get_cibfile_cksum(cibname):
    """
    Get the full path of the file containing a checksum of a CIB-file with the name of the CIB
    """
    cibfile_cksum = f"{_get_cibfile(cibname)}.cksum"
    log.trace("cibfile_cksum: %s", cibfile_cksum)
    return cibfile_cksum


def _get_node_list_for_version(nodes):
    """
    PCS with version < 0.10 returns lowercase hostnames. Newer versions return the proper hostnames.
    This accomodates for the old functionality.
    """
    pcs_version = __salt__["pkg.version"]("pcs")
    if __salt__["pkg.version_cmp"](pcs_version, "0.10") == -1:
        log.info("Node list converted to lower case for backward compatibility")
        nodes_for_version = [x.lower() for x in nodes]
    else:
        nodes_for_version = nodes
    return nodes_for_version


def _item_present(
    name,
    item,
    item_id,
    item_type,
    show="show",
    create="create",
    extra_args=None,
    cibname=None,
):
    """
    Ensure that an item is created

    name
        Irrelevant, not used
    item
        config, property, resource, constraint etc.
    item_id
        id of the item
    item_type
        item type
    show
        show command (probably None, default: show)
    create
        create command (create or set f.e., default: create)
    extra_args
        additional options for the pcs command
    cibname
        use a cached CIB-file named like cibname instead of the live CIB
    """
    ret = {"name": name, "result": True, "comment": "", "changes": {}}
    item_create_required = True

    cibfile = None
    if isinstance(cibname, str):
        cibfile = _get_cibfile(cibname)

    if not isinstance(extra_args, (list, tuple)):
        extra_args = []

    # split off key and value (item_id contains =)
    item_id_key = item_id
    item_id_value = None
    if "=" in item_id:
        item_id_key = item_id.split("=")[0].strip()
        item_id_value = item_id.replace(item_id.split("=")[0] + "=", "").strip()
        log.trace("item_id_key=%s item_id_value=%s", item_id_key, item_id_value)

    # constraints, properties, resource defaults or resource op defaults
    # do not support specifying an id on 'show' command
    item_id_show = item_id
    if item in ["constraint"] or "=" in item_id:
        item_id_show = None

    is_existing = __salt__["pcs.item_show"](
        item=item, item_id=item_id_show, item_type=item_type, show=show, cibfile=cibfile
    )
    log.trace(
        "Output of pcs.item_show item=%s item_id=%s item_type=%s cibfile=%s: %s",
        item,
        item_id_show,
        item_type,
        cibfile,
        is_existing,
    )

    # key,value pairs (item_id contains =) - match key and value
    if item_id_value is not None:
        for line in is_existing["stdout"].splitlines():
            if len(line.split(":")) in [2]:
                key = line.split(":")[0].strip()
                value = line.split(":")[1].strip()
                if item_id_key in [key]:
                    if item_id_value in [value]:
                        item_create_required = False

    # constraints match on '(id:<id>)'
    elif item in ["constraint"]:
        for line in is_existing["stdout"].splitlines():
            if f"(id:{item_id})" in line:
                item_create_required = False

    # item_id was provided,
    # return code 0 indicates, that resource already exists
    else:
        if is_existing["retcode"] in [0]:
            item_create_required = False

    if not item_create_required:
        ret["comment"] += "{} {} ({}) is already existing\n".format(
            str(item), str(item_id), str(item_type)
        )
        return ret

    if __opts__["test"]:
        ret["result"] = None
        ret["comment"] += "{} {} ({}) is set to be created\n".format(
            str(item), str(item_id), str(item_type)
        )
        return ret

    item_create = __salt__["pcs.item_create"](
        item=item,
        item_id=item_id,
        item_type=item_type,
        create=create,
        extra_args=extra_args,
        cibfile=cibfile,
    )

    log.trace("Output of pcs.item_create: %s", item_create)

    if item_create["retcode"] in [0]:
        ret["comment"] += f"Created {item} {item_id} ({item_type})\n"
        ret["changes"].update({item_id: {"old": "", "new": str(item_id)}})
    else:
        ret["result"] = False
        ret["comment"] += "Failed to create {} {} ({})\n".format(
            item, item_id, item_type
        )

    log.trace("ret: %s", ret)

    return ret


def auth(name, nodes, pcsuser="hacluster", pcspasswd="hacluster", extra_args=None):
    """
    Ensure all nodes are authorized to the cluster

    name
        Irrelevant, not used (recommended: pcs_auth__auth)
    nodes
        a list of nodes which should be authorized to the cluster
    pcsuser
        user for communication with pcs (default: hacluster)
    pcspasswd
        password for pcsuser (default: hacluster)
    extra_args
        list of extra args for the \'pcs cluster auth\' command, there are none so it's here for compatibility.

    Example:

    .. code-block:: yaml

        pcs_auth__auth:
            pcs.auth:
                - nodes:
                    - node1.example.com
                    - node2.example.com
                - pcsuser: hacluster
                - pcspasswd: hoonetorg
                - extra_args: []
    """

    ret = {"name": name, "result": True, "comment": "", "changes": {}}
    auth_required = False

    nodes = _get_node_list_for_version(nodes)

    authorized = __salt__["pcs.is_auth"](
        nodes=nodes, pcsuser=pcsuser, pcspasswd=pcspasswd
    )
    log.trace("Output of pcs.is_auth: %s", authorized)

    authorized_dict = {}
    for line in authorized["stdout"].splitlines():
        node = line.split(":")[0].strip()
        auth_state = line.split(":")[1].strip()
        if node in nodes:
            authorized_dict.update({node: auth_state})
    log.trace("authorized_dict: %s", authorized_dict)

    for node in nodes:
        if node in authorized_dict and (
            authorized_dict[node] == "Already authorized"
            or authorized_dict[node] == "Authorized"
        ):
            ret["comment"] += f"Node {node} is already authorized\n"
        else:
            auth_required = True
            if __opts__["test"]:
                ret["comment"] += f"Node is set to authorize: {node}\n"

    if not auth_required:
        return ret

    if __opts__["test"]:
        ret["result"] = None
        return ret

    authorize = __salt__["pcs.auth"](
        nodes=nodes, pcsuser=pcsuser, pcspasswd=pcspasswd, extra_args=extra_args
    )
    log.trace("Output of pcs.auth: %s", authorize)

    authorize_dict = {}
    for line in authorize["stdout"].splitlines():
        node = line.split(":")[0].strip()
        auth_state = line.split(":")[1].strip()
        if node in nodes:
            authorize_dict.update({node: auth_state})
    log.trace("authorize_dict: %s", authorize_dict)

    for node in nodes:
        if node in authorize_dict and authorize_dict[node] == "Authorized":
            ret["comment"] += f"Authorized {node}\n"
            ret["changes"].update({node: {"old": "", "new": "Authorized"}})
        else:
            ret["result"] = False
            if node in authorized_dict:
                ret[
                    "comment"
                ] += "Authorization check for node {} returned: {}\n".format(
                    node, authorized_dict[node]
                )
            if node in authorize_dict:
                ret["comment"] += "Failed to authorize {} with error {}\n".format(
                    node, authorize_dict[node]
                )

    return ret


def cluster_setup(
    name,
    nodes,
    pcsclustername="pcscluster",
    extra_args=None,
    pcsuser="hacluster",
    pcspasswd="hacluster",
    pcs_auth_extra_args=None,
    wipe_default=False,
):
    """
    Setup Pacemaker cluster on nodes.
    Should be run on one cluster node only to avoid race conditions.
    This performs auth as well as setup so can be run in place of the auth state.
    It is recommended not to run auth on Debian/Ubuntu for a new cluster and just
    to run this because of the initial cluster config that is installed on
    Ubuntu/Debian by default.


    name
        Irrelevant, not used (recommended: pcs_setup__setup)
    nodes
        a list of nodes which should be set up
    pcsclustername
        Name of the Pacemaker cluster
    extra_args
        list of extra args for the \'pcs cluster setup\' command
    pcsuser
        The username for authenticating the cluster (default: hacluster)
    pcspasswd
        The password for authenticating the cluster (default: hacluster)
    pcs_auth_extra_args
        Extra args to be passed to the auth function in case of reauth.
    wipe_default
        This removes the files that are installed with Debian based operating systems.

    Example:

    .. code-block:: yaml

        pcs_setup__setup:
            pcs.cluster_setup:
                - nodes:
                    - node1.example.com
                    - node2.example.com
                - pcsclustername: pcscluster
                - extra_args:
                    - '--start'
                    - '--enable'
                - pcsuser: hacluster
                - pcspasswd: hoonetorg
    """

    ret = {"name": name, "result": True, "comment": "", "changes": {}}
    setup_required = False

    config_show = __salt__["pcs.config_show"]()
    log.trace("Output of pcs.config_show: %s", config_show)

    for line in config_show["stdout"].splitlines():
        if len(line.split(":")) in [2]:
            key = line.split(":")[0].strip()
            value = line.split(":")[1].strip()
            if key in ["Cluster Name"]:
                if value in [pcsclustername]:
                    ret["comment"] += "Cluster {} is already set up\n".format(
                        pcsclustername
                    )
                else:
                    setup_required = True
                    if __opts__["test"]:
                        ret["comment"] += "Cluster {} is set to set up\n".format(
                            pcsclustername
                        )

    if not setup_required:
        log.info("No setup required")
        return ret

    if __opts__["test"]:
        ret["result"] = None
        return ret

    # Debian based distros deploy corosync with some initial cluster setup.
    # The following detects if it's a Debian based distro and then stops Corosync
    # and removes the config files. I've put this here because trying to do all this in the
    # state file can break running clusters and can also take quite a long time to debug.

    log.debug("OS_Family: %s", __grains__.get("os_family"))
    if __grains__.get("os_family") == "Debian" and wipe_default:
        __salt__["file.remove"]("/etc/corosync/corosync.conf")
        __salt__["file.remove"]("/var/lib/pacemaker/cib/cib.xml")
        __salt__["service.stop"]("corosync")
        auth("pcs_auth__auth", nodes, pcsuser, pcspasswd, pcs_auth_extra_args)

    nodes = _get_node_list_for_version(nodes)

    if not isinstance(extra_args, (list, tuple)):
        extra_args = []

    setup = __salt__["pcs.cluster_setup"](
        nodes=nodes, pcsclustername=pcsclustername, extra_args=extra_args
    )
    log.trace("Output of pcs.cluster_setup: %s", setup)

    setup_dict = {}
    for line in setup["stdout"].splitlines():
        log.trace("line: %s", line)
        log.trace("line.split(:).len: %s", len(line.split(":")))
        if len(line.split(":")) in [2]:
            node = line.split(":")[0].strip()
            setup_state = line.split(":")[1].strip()
            if node in nodes:
                setup_dict.update({node: setup_state})

    log.trace("setup_dict: %s", setup_dict)

    for node in nodes:
        if node in setup_dict and setup_dict[node] in [
            "Succeeded",
            "Success",
            "Cluster enabled",
        ]:
            ret["comment"] += f"Set up {node}\n"
            ret["changes"].update({node: {"old": "", "new": "Setup"}})
        else:
            ret["result"] = False
            ret["comment"] += f"Failed to setup {node}\n"
            if node in setup_dict:
                ret["comment"] += f"{node}: setup_dict: {setup_dict[node]}\n"
            ret["comment"] += str(setup)

    log.trace("ret: %s", ret)

    return ret


def cluster_node_present(name, node, extra_args=None):
    """
    Add a node to the Pacemaker cluster via PCS
    Should be run on one cluster node only
    (there may be races)
    Can only be run on a already setup/added node

    name
        Irrelevant, not used (recommended: pcs_setup__node_add_{{node}})
    node
        node that should be added
    extra_args
        list of extra args for the \'pcs cluster node add\' command

    Example:

    .. code-block:: yaml

        pcs_setup__node_add_node1.example.com:
            pcs.cluster_node_present:
                - node: node1.example.com
                - extra_args:
                    - '--start'
                    - '--enable'
    """

    ret = {"name": name, "result": True, "comment": "", "changes": {}}
    node_add_required = True
    current_nodes = []

    is_member_cmd = ["pcs", "status", "nodes", "corosync"]
    is_member = __salt__["cmd.run_all"](
        is_member_cmd, output_loglevel="trace", python_shell=False
    )
    log.trace("Output of pcs status nodes corosync: %s", is_member)

    for line in is_member["stdout"].splitlines():
        if len(line.split(":")) in [2]:
            key = line.split(":")[0].strip()
            value = line.split(":")[1].strip()
            if key in ["Offline", "Online"]:
                if len(value.split()) > 0:
                    if node in value.split():
                        node_add_required = False
                        ret[
                            "comment"
                        ] += f"Node {node} is already member of the cluster\n"
                    else:
                        current_nodes += value.split()

    if not node_add_required:
        return ret

    if __opts__["test"]:
        ret["result"] = None
        ret["comment"] += f"Node {node} is set to be added to the cluster\n"
        return ret

    if not isinstance(extra_args, (list, tuple)):
        extra_args = []

    node_add = __salt__["pcs.cluster_node_add"](node=node, extra_args=extra_args)
    log.trace("Output of pcs.cluster_node_add: %s", node_add)

    node_add_dict = {}
    for line in node_add["stdout"].splitlines():
        log.trace("line: %s", line)
        log.trace("line.split(:).len: %s", len(line.split(":")))
        if len(line.split(":")) in [2]:
            current_node = line.split(":")[0].strip()
            current_node_add_state = line.split(":")[1].strip()
            if current_node in current_nodes + [node]:
                node_add_dict.update({current_node: current_node_add_state})
    log.trace("node_add_dict: %s", node_add_dict)

    for current_node in current_nodes:
        if current_node in node_add_dict:
            if node_add_dict[current_node] not in ["Corosync updated"]:
                ret["result"] = False
                ret["comment"] += "Failed to update corosync.conf on node {}\n".format(
                    current_node
                )
                ret["comment"] += "{}: node_add_dict: {}\n".format(
                    current_node, node_add_dict[current_node]
                )
        else:
            ret["result"] = False
            ret["comment"] += "Failed to update corosync.conf on node {}\n".format(
                current_node
            )

    if node in node_add_dict and node_add_dict[node] in ["Succeeded", "Success"]:
        ret["comment"] += f"Added node {node}\n"
        ret["changes"].update({node: {"old": "", "new": "Added"}})
    else:
        ret["result"] = False
        ret["comment"] += f"Failed to add node{node}\n"
        if node in node_add_dict:
            ret["comment"] += "{}: node_add_dict: {}\n".format(
                node, node_add_dict[node]
            )
        ret["comment"] += str(node_add)

    log.trace("ret: %s", ret)

    return ret


def cib_present(name, cibname, scope=None, extra_args=None):
    """
    Ensure that a CIB-file with the content of the current live CIB is created

    Should be run on one cluster node only
    (there may be races)

    name
        Irrelevant, not used (recommended: {{formulaname}}__cib_present_{{cibname}})
    cibname
        name/path of the file containing the CIB
    scope
        specific section of the CIB (default: None)
    extra_args
        additional options for creating the CIB-file

    Example:

    .. code-block:: yaml

        mysql_pcs__cib_present_cib_for_galera:
            pcs.cib_present:
                - cibname: cib_for_galera
                - scope: None
                - extra_args: None
    """
    ret = {"name": name, "result": True, "comment": "", "changes": {}}

    cib_hash_form = "sha256"

    cib_create_required = False
    cib_cksum_required = False
    cib_required = False

    cibpath = _get_cibpath()
    cibfile = _get_cibfile(cibname)
    cibfile_tmp = _get_cibfile_tmp(cibname)
    cibfile_cksum = _get_cibfile_cksum(cibname)

    if not os.path.exists(cibpath):
        os.makedirs(cibpath)

    if not isinstance(extra_args, (list, tuple)):
        extra_args = []

    if os.path.exists(cibfile_tmp):
        __salt__["file.remove"](cibfile_tmp)

    cib_create = __salt__["pcs.cib_create"](
        cibfile=cibfile_tmp, scope=scope, extra_args=extra_args
    )
    log.trace("Output of pcs.cib_create: %s", cib_create)

    if cib_create["retcode"] not in [0] or not os.path.exists(cibfile_tmp):
        ret["result"] = False
        ret["comment"] += "Failed to get live CIB\n"
        return ret

    cib_hash_live = "{}:{}".format(
        cib_hash_form, __salt__["file.get_hash"](path=cibfile_tmp, form=cib_hash_form)
    )
    log.trace("cib_hash_live: %s", cib_hash_live)

    cib_hash_cur = _file_read(path=cibfile_cksum)

    if cib_hash_cur not in [cib_hash_live]:
        cib_cksum_required = True

    log.trace("cib_hash_cur: %s", cib_hash_cur)

    if not os.path.exists(cibfile) or not __salt__["file.check_hash"](
        path=cibfile, file_hash=cib_hash_live
    ):
        cib_create_required = True

    if cib_cksum_required or cib_create_required:
        cib_required = True

    if not cib_create_required:
        __salt__["file.remove"](cibfile_tmp)
        ret["comment"] += f"CIB {cibname} is already equal to the live CIB\n"

    if not cib_cksum_required:
        ret["comment"] += f"CIB {cibname} checksum is correct\n"

    if not cib_required:
        return ret

    if __opts__["test"]:
        __salt__["file.remove"](cibfile_tmp)
        ret["result"] = None
        if cib_create_required:
            ret["comment"] += f"CIB {cibname} is set to be created/updated\n"
        if cib_cksum_required:
            ret["comment"] += "CIB {} checksum is set to be created/updated\n".format(
                cibname
            )
        return ret

    if cib_create_required:
        __salt__["file.move"](cibfile_tmp, cibfile)

        if __salt__["file.check_hash"](path=cibfile, file_hash=cib_hash_live):
            ret["comment"] += f"Created/updated CIB {cibname}\n"
            ret["changes"].update({"cibfile": cibfile})
        else:
            ret["result"] = False
            ret["comment"] += f"Failed to create/update CIB {cibname}\n"

    if cib_cksum_required:
        _file_write(cibfile_cksum, cib_hash_live)

        if _file_read(cibfile_cksum) in [cib_hash_live]:
            ret["comment"] += "Created/updated checksum {} of CIB {}\n".format(
                cib_hash_live, cibname
            )
            ret["changes"].update({"cibcksum": cib_hash_live})
        else:
            ret["result"] = False
            ret["comment"] += "Failed to create/update checksum {} CIB {}\n".format(
                cib_hash_live, cibname
            )

    log.trace("ret: %s", ret)

    return ret


def cib_pushed(name, cibname, scope=None, extra_args=None):
    """
    Ensure that a CIB-file is pushed if it is changed since the creation of it with pcs.cib_present

    Should be run on one cluster node only
    (there may be races)

    name
        Irrelevant, not used (recommended: {{formulaname}}__cib_pushed_{{cibname}})
    cibname
        name/path of the file containing the CIB
    scope
        specific section of the CIB
    extra_args
        additional options for creating the CIB-file

    Example:

    .. code-block:: yaml

        mysql_pcs__cib_pushed_cib_for_galera:
            pcs.cib_pushed:
                - cibname: cib_for_galera
                - scope: None
                - extra_args: None
    """
    ret = {"name": name, "result": True, "comment": "", "changes": {}}

    cib_hash_form = "sha256"

    cib_push_required = False

    cibfile = _get_cibfile(cibname)
    cibfile_cksum = _get_cibfile_cksum(cibname)

    if not isinstance(extra_args, (list, tuple)):
        extra_args = []

    if not os.path.exists(cibfile):
        ret["result"] = False
        ret["comment"] += f"CIB-file {cibfile} does not exist\n"
        return ret

    cib_hash_cibfile = "{}:{}".format(
        cib_hash_form, __salt__["file.get_hash"](path=cibfile, form=cib_hash_form)
    )
    log.trace("cib_hash_cibfile: %s", cib_hash_cibfile)

    if _file_read(cibfile_cksum) not in [cib_hash_cibfile]:
        cib_push_required = True

    if not cib_push_required:
        ret[
            "comment"
        ] += "CIB {} is not changed since creation through pcs.cib_present\n".format(
            cibname
        )
        return ret

    if __opts__["test"]:
        ret["result"] = None
        ret["comment"] += "CIB {} is set to be pushed as the new live CIB\n".format(
            cibname
        )
        return ret

    cib_push = __salt__["pcs.cib_push"](
        cibfile=cibfile, scope=scope, extra_args=extra_args
    )
    log.trace("Output of pcs.cib_push: %s", cib_push)

    if cib_push["retcode"] in [0]:
        ret["comment"] += f"Pushed CIB {cibname}\n"
        ret["changes"].update({"cibfile_pushed": cibfile})
    else:
        ret["result"] = False
        ret["comment"] += f"Failed to push CIB {cibname}\n"

    log.trace("ret: %s", ret)

    return ret


def prop_has_value(name, prop, value, extra_args=None, cibname=None):
    """
    Ensure that a property in the cluster is set to a given value

    Should be run on one cluster node only
    (there may be races)

    name
        Irrelevant, not used (recommended: pcs_properties__prop_has_value_{{prop}})
    prop
        name of the property
    value
        value of the property
    extra_args
        additional options for the pcs property command
    cibname
        use a cached CIB-file named like cibname instead of the live CIB

    Example:

    .. code-block:: yaml

        pcs_properties__prop_has_value_no-quorum-policy:
            pcs.prop_has_value:
                - prop: no-quorum-policy
                - value: ignore
                - cibname: cib_for_cluster_settings
    """
    return _item_present(
        name=name,
        item="property",
        item_id=f"{prop}={value}",
        item_type=None,
        create="set",
        extra_args=extra_args,
        cibname=cibname,
    )


def resource_defaults_to(name, default, value, extra_args=None, cibname=None):
    """
    Ensure a resource default in the cluster is set to a given value

    Should be run on one cluster node only
    (there may be races)
    Can only be run on a node with a functional pacemaker/corosync

    name
        Irrelevant, not used (recommended: pcs_properties__resource_defaults_to_{{default}})
    default
        name of the default resource property
    value
        value of the default resource property
    extra_args
        additional options for the pcs command
    cibname
        use a cached CIB-file named like cibname instead of the live CIB

    Example:

    .. code-block:: yaml

        pcs_properties__resource_defaults_to_resource-stickiness:
            pcs.resource_defaults_to:
                - default: resource-stickiness
                - value: 100
                - cibname: cib_for_cluster_settings
    """
    return _item_present(
        name=name,
        item="resource",
        item_id=f"{default}={value}",
        item_type=None,
        show="defaults",
        create="defaults",
        extra_args=extra_args,
        cibname=cibname,
    )


def resource_op_defaults_to(name, op_default, value, extra_args=None, cibname=None):
    """
    Ensure a resource operation default in the cluster is set to a given value

    Should be run on one cluster node only
    (there may be races)
    Can only be run on a node with a functional pacemaker/corosync

    name
        Irrelevant, not used (recommended: pcs_properties__resource_op_defaults_to_{{op_default}})
    op_default
        name of the operation default resource property
    value
        value of the operation default resource property
    extra_args
        additional options for the pcs command
    cibname
        use a cached CIB-file named like cibname instead of the live CIB

    Example:

    .. code-block:: yaml

        pcs_properties__resource_op_defaults_to_monitor-interval:
            pcs.resource_op_defaults_to:
                - op_default: monitor-interval
                - value: 60s
                - cibname: cib_for_cluster_settings
    """
    return _item_present(
        name=name,
        item="resource",
        item_id=f"{op_default}={value}",
        item_type=None,
        show=["op", "defaults"],
        create=["op", "defaults"],
        extra_args=extra_args,
        cibname=cibname,
    )


def stonith_present(
    name, stonith_id, stonith_device_type, stonith_device_options=None, cibname=None
):
    """
    Ensure that a fencing resource is created

    Should be run on one cluster node only
    (there may be races)
    Can only be run on a node with a functional pacemaker/corosync

    name
        Irrelevant, not used (recommended: pcs_stonith__created_{{stonith_id}})
    stonith_id
        name for the stonith resource
    stonith_device_type
        name of the stonith agent fence_eps, fence_xvm f.e.
    stonith_device_options
        additional options for creating the stonith resource
    cibname
        use a cached CIB-file named like cibname instead of the live CIB

    Example:

    .. code-block:: yaml

        pcs_stonith__created_eps_fence:
            pcs.stonith_present:
                - stonith_id: eps_fence
                - stonith_device_type: fence_eps
                - stonith_device_options:
                    - 'pcmk_host_map=node1.example.org:01;node2.example.org:02'
                    - 'ipaddr=myepsdevice.example.org'
                    - 'power_wait=5'
                    - 'verbose=1'
                    - 'debug=/var/log/pcsd/eps_fence.log'
                    - 'login=hidden'
                    - 'passwd=hoonetorg'
                - cibname: cib_for_stonith
    """
    return _item_present(
        name=name,
        item="stonith",
        item_id=stonith_id,
        item_type=stonith_device_type,
        extra_args=stonith_device_options,
        cibname=cibname,
    )


def resource_present(
    name, resource_id, resource_type, resource_options=None, cibname=None
):
    """
    Ensure that a resource is created

    Should be run on one cluster node only
    (there may be races)
    Can only be run on a node with a functional pacemaker/corosync

    name
        Irrelevant, not used (recommended: {{formulaname}}__resource_present_{{resource_id}})
    resource_id
        name for the resource
    resource_type
        resource type (f.e. ocf:heartbeat:IPaddr2 or VirtualIP)
    resource_options
        additional options for creating the resource
    cibname
        use a cached CIB-file named like cibname instead of the live CIB

    Example:

    .. code-block:: yaml

        mysql_pcs__resource_present_galera:
            pcs.resource_present:
                - resource_id: galera
                - resource_type: "ocf:heartbeat:galera"
                - resource_options:
                    - 'wsrep_cluster_address=gcomm://node1.example.org,node2.example.org,node3.example.org'
                    - '--master'
                - cibname: cib_for_galera
    """
    return _item_present(
        name=name,
        item="resource",
        item_id=resource_id,
        item_type=resource_type,
        extra_args=resource_options,
        cibname=cibname,
    )


def constraint_present(
    name, constraint_id, constraint_type, constraint_options=None, cibname=None
):
    """
    Ensure that a constraint is created

    Should be run on one cluster node only
    (there may be races)
    Can only be run on a node with a functional pacemaker/corosync

    name
        Irrelevant, not used (recommended: {{formulaname}}__constraint_present_{{constraint_id}})
    constraint_id
        name for the constraint (try first to create manually to find out the autocreated name)
    constraint_type
        constraint type (location, colocation, order)
    constraint_options
        options for creating the constraint
    cibname
        use a cached CIB-file named like cibname instead of the live CIB

    Example:

    .. code-block:: yaml

        haproxy_pcs__constraint_present_colocation-vip_galera-haproxy-clone-INFINITY:
            pcs.constraint_present:
                - constraint_id: colocation-vip_galera-haproxy-clone-INFINITY
                - constraint_type: colocation
                - constraint_options:
                    - 'add'
                    - 'vip_galera'
                    - 'with'
                    - 'haproxy-clone'
                - cibname: cib_for_haproxy
    """
    return _item_present(
        name=name,
        item="constraint",
        item_id=constraint_id,
        item_type=constraint_type,
        create=None,
        extra_args=constraint_options,
        cibname=cibname,
    )
