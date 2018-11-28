# Copyright (C) 2018 AT&T
# Copyright (C) 2016 Midokura SARL.
# Copyright (C) 2015 Ericsson AB
# Copyright (c) 2015 Gigamon
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutron.common import rpc as n_rpc
from neutron.extensions import portbindings
from neutron_lib import constants
from neutron_lib import exceptions as n_exc

from neutron_taas.common import constants as taas_consts
from neutron_taas.common import topics
from neutron_taas.common import utils as common_utils
from neutron_taas.services.taas import service_drivers
from neutron_taas.services.taas.service_drivers import taas_agent_api

from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class TaasRpcDriver(service_drivers.TaasBaseDriver):
    """Taas Rpc Service Driver class"""

    def __init__(self, service_plugin):
        LOG.debug("Loading TaasRpcDriver.")
        super(TaasRpcDriver, self).__init__(service_plugin)
        self.endpoints = [taas_agent_api.TaasCallbacks(service_plugin)]
        self.conn = n_rpc.Connection()
        self.conn.create_consumer(topics.TAAS_PLUGIN,
                                  self.endpoints, fanout=False)

        self.conn.consume_in_threads()

        self.agent_rpc = taas_agent_api.TaasAgentApi(
            topics.TAAS_AGENT,
            cfg.CONF.host
        )

        return

    def _get_taas_id(self, context, tf):
        ts = self.service_plugin.get_tap_service(context,
                                                 tf['tap_service_id'])
        taas_id = (self.service_plugin.get_tap_id_association(
            context,
            tap_service_id=ts['id']))['taas_id']
        return taas_id

    def create_tap_service_precommit(self, context):
        ts = context.tap_service
        tap_id_association = context._plugin.create_tap_id_association(
            context._plugin_context, ts['id'])
        context.tap_id_association = tap_id_association

    def create_tap_service_postcommit(self, context):
        """Send tap service creation RPC message to agent.

        This RPC message includes taas_id that is added vlan_range_start to
        so that taas-ovs-agent can use taas_id as VLANID.
        """
        # Get taas id associated with the Tap Service
        ts = context.tap_service
        tap_id_association = context.tap_id_association
        taas_vlan_id = tap_id_association['taas_id']
        port = self.service_plugin._get_port_details(context._plugin_context,
                                                     ts['port_id'])
        host = port['binding:host_id']

        rpc_msg = {'tap_service': ts,
                   'taas_id': taas_vlan_id,
                   'port': port}

        self.agent_rpc.create_tap_service(context._plugin_context,
                                          rpc_msg, host)
        return

    def delete_tap_service_precommit(self, context):
        pass

    def delete_tap_service_postcommit(self, context):
        """Send tap service deletion RPC message to agent.

        This RPC message includes taas_id that is added vlan_range_start to
        so that taas-ovs-agent can use taas_id as VLANID.
        """
        ts = context.tap_service
        tap_id_association = context.tap_id_association
        taas_vlan_id = tap_id_association['taas_id']

        try:
            port = self.service_plugin._get_port_details(
                context._plugin_context,
                ts['port_id'])
            host = port['binding:host_id']
        except n_exc.PortNotFound:
            # if not found, we just pass to None
            port = None
            host = None

        rpc_msg = {'tap_service': ts,
                   'taas_id': taas_vlan_id,
                   'port': port}

        self.agent_rpc.delete_tap_service(context._plugin_context,
                                          rpc_msg, host)
        return

    def create_tap_flow_precommit(self, context):
        pass

    def create_tap_flow_postcommit(self, context):
        """Send tap flow creation RPC message to agent."""
        tf = context.tap_flow
        taas_id = self._get_taas_id(context._plugin_context, tf)
        # Extract the host where the source port is located
        port = self.service_plugin._get_port_details(context._plugin_context,
                                                     tf['source_port'])
        host = port['binding:host_id']
        port_mac = port['mac_address']
        # Extract the tap-service port
        ts = self.service_plugin.get_tap_service(context._plugin_context,
                                                 tf['tap_service_id'])
        ts_port = self.service_plugin._get_port_details(
            context._plugin_context, ts['port_id'])

        # Check if same VLAN is being used already in some other tap flow
        if port.get(portbindings.VNIC_TYPE) == portbindings.VNIC_DIRECT:
            # Get all the active tap flows
            active_tfs = self.service_plugin.get_tap_flows(
                context._plugin_context,
                filters={'status': [constants.ACTIVE]},
                fields=['source_port', 'tap_service_id', 'vlan_filter'])

            # Filter out the tap flows associated with distinct tap services
            tf_iter = (tflow for tap_flow in active_tfs
                       if (tflow['tap_service_id'] != tf['tap_service_id']))

            for tf_existing in tf_iter:
                src_port_existing = self.service_plugin._get_port_details(
                    context._plugin_context, tf_existing['source_port'])

                ts_existing = self.service_plugin.get_tap_service(
                    context._plugin_context, tf_existing['tap_service_id'])

                dest_port_existing = self.service_plugin._get_port_details(
                    context._plugin_context, ts_existing['port_id'])

                if (src_port_existing['binding:host_id'] != host) or \
                        (dest_port_existing['binding:host_id'] != \
                            ts_port['binding:host_id']):
                    continue

                vlan_filter_list_iter = sorted(
                    set(common_utils.get_list_from_ranges_str(
                        tf_existing['vlan_filter'])))
                vlan_filter_list_curr = sorted(
                    set(common_utils.get_list_from_ranges_str(
                        tf['vlan_filter'])))

                overlapping_vlans = list(set(
                    vlan_filter_iter_list).intersection(vlan_filter_curr_list)

                if overlapping_vlans != []):
                    LOG.error("taas: same VLAN Ids can't associate with"
                              "multiple tap-services. These VLAN Ids:"
                              "[%(overlapping_vlans)s] overlap with existing"
                              "tap-services.",
                              {'overlapping_vlans': overlapping_vlans})
                    return

        # Send RPC message to both the source port host and
        # tap service(destination) port host
        rpc_msg = {'tap_flow': tf,
                   'port_mac': port_mac,
                   'taas_id': taas_id,
                   'port': port,
                   'tap_service_port': ts_port}

        self.agent_rpc.create_tap_flow(context._plugin_context, rpc_msg, host)
        return

    def delete_tap_flow_precommit(self, context):
        pass

    def delete_tap_flow_postcommit(self, context):
        """Send tap flow deletion RPC message to agent."""
        tf = context.tap_flow
        taas_id = self._get_taas_id(context._plugin_context, tf)
        # Extract the host where the source port is located
        port = self.service_plugin._get_port_details(context._plugin_context,
                                                     tf['source_port'])
        host = port['binding:host_id']
        port_mac = port['mac_address']
        # Extract the tap-service port
        ts = self.service_plugin.get_tap_service(context._plugin_context,
                                                 tf['tap_service_id'])
        ts_port = self.service_plugin._get_port_details(
            context._plugin_context, ts['port_id'])

        src_vlans_list = []
        vlan_filter_list = []

        if port.get(portbindings.VNIC_TYPE) == portbindings.VNIC_DIRECT:
            # Get all the tap Flows that are associated with the Tap service
            active_tfs = self.service_plugin.get_tap_flows(
                context._plugin_context,
                filters={'tap_service_id': [tf['tap_service_id']],
                         'status': [constants.ACTIVE]},
                fields=['source_port', 'vlan_filter'])

            for tap_flow in active_tfs:
                source_port = self.service_plugin._get_port_details(
                    context._plugin_context, tap_flow['source_port'])

                LOG.debug("taas: active TF's source_port %(source_port)s",
                          {'source_port': source_port})

                src_vlans = ""
                if source_port.get(portbindings.VIF_DETAILS):
                    src_vlans = source_port[portbindings.VIF_DETAILS].get(
                        portbindings.VIF_DETAILS_VLAN)

                # If no VLAN filter configured on source port,
                # then include all vlans
                if not src_vlans or src_vlans == '0':
                    src_vlans = taas_consts.VLAN_RANGE

                src_vlans_list.append(src_vlans)

                vlan_filter = tap_flow['vlan_filter']
                # If no VLAN filter configured for tap-flow,
                # then include all vlans
                if not vlan_filter:
                    vlan_filter = taas_consts.VLAN_RANGE

                vlan_filter_list.append(vlan_filter)

        # Send RPC message to both the source port host and
        # tap service(destination) port host
        rpc_msg = {'tap_flow': tf,
                   'port_mac': port_mac,
                   'taas_id': taas_id,
                   'port': port,
                   'tap_service_port': ts_port,
                   'source_vlans_list': src_vlans_list,
                   'vlan_filter_list': vlan_filter_list}

        self.agent_rpc.delete_tap_flow(context._plugin_context, rpc_msg, host)
        return
