# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 IBM
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
from lxml import etree
from tempest import exceptions
from tempest.common.rest_client import RestClientXML
from tempest.services.nova.xml.common import Document
from tempest.services.nova.xml.common import Element
from tempest.services.nova.xml.common import Text
from tempest.services.nova.xml.common import xml_to_json
from tempest.services.nova.xml.common import XMLNS_11
import time

LOG = logging.getLogger(__name__)


class ServersClientXML(RestClientXML):

    def __init__(self, config, username, password, auth_url, tenant_name=None):
        super(ServersClientXML, self).__init__(config, username, password,
                                               auth_url, tenant_name)
        self.service = self.config.compute.catalog_type

    def _parse_key_value(self, node):
        """Parse <foo key='key'>value</foo> data into {'key': 'value'}"""
        data = {}
        for node in node.getchildren():
            data[node.get('key')] = node.text
        return data

    def _parse_links(self, node, json):
        del json['link']
        json['links'] = []
        for linknode in node.findall('{http://www.w3.org/2005/Atom}link'):
            json['links'].append(xml_to_json(linknode))

    def _parse_server(self, body):
        json = xml_to_json(body)
        if 'metadata' in json and json['metadata']:
            # NOTE(danms): if there was metadata, we need to re-parse
            # that as a special type
            metadata_tag = body.find('{%s}metadata' % XMLNS_11)
            json["metadata"] = self._parse_key_value(metadata_tag)
        if 'link' in json:
            self._parse_links(body, json)
        for sub in ['image', 'flavor']:
            if sub in json and 'link' in json[sub]:
                self._parse_links(body, json[sub])

        return json

    def get_server(self, server_id):
        """Returns the details of an existing server"""
        resp, body = self.get("servers/%s" % str(server_id), self.headers)
        server = self._parse_server(etree.fromstring(body))
        return resp, server

    def delete_server(self, server_id):
        """Deletes the given server"""
        return self.delete("servers/%s" % str(server_id))

    def _parse_array(self, node):
        array = []
        for child in node.getchildren():
            array.append(xml_to_json(child))
        return array

    def list_servers(self, params=None):
        url = 'servers/detail'
        if params is not None:
            param_list = []
            for param, value in params.iteritems():
                param_list.append("%s=%s" % (param, value))

            url += "?" + "&".join(param_list)
        resp, body = self.get(url, self.headers)
        servers = self._parse_array(etree.fromstring(body))
        return resp, {"servers": servers}

    def list_servers_with_detail(self, params=None):
        url = 'servers/detail'
        if params is not None:
            param_list = []
            for param, value in params.iteritems():
                param_list.append("%s=%s" % (param, value))

            url += "?" + "&".join(param_list)
        resp, body = self.get(url, self.headers)
        servers = self._parse_array(etree.fromstring(body))
        return resp, {"servers": servers}

    def update_server(self, server_id, name=None, meta=None, accessIPv4=None,
                      accessIPv6=None):
        doc = Document()
        server = Element("server")
        doc.append(server)

        if name:
            server.add_attr("name", name)
        if accessIPv4:
            server.add_attr("accessIPv4", accessIPv4)
        if accessIPv6:
            server.add_attr("accessIPv6", accessIPv6)
        if meta:
            metadata = Element("metadata")
            server.append(metadata)
            for k, v in meta:
                meta = Element("meta", key=k)
                meta.append(Text(v))
                metadata.append(meta)

        resp, body = self.put('servers/%s' % str(server_id),
                              str(doc), self.headers)
        return resp, xml_to_json(etree.fromstring(body))

    def create_server(self, name, image_ref, flavor_ref, **kwargs):
        """
        Creates an instance of a server.
        name (Required): The name of the server.
        image_ref (Required): Reference to the image used to build the server.
        flavor_ref (Required): The flavor used to build the server.
        Following optional keyword arguments are accepted:
        adminPass: Sets the initial root password.
        key_name: Key name of keypair that was created earlier.
        meta: A dictionary of values to be used as metadata.
        personality: A list of dictionaries for files to be injected into
        the server.
        security_groups: A list of security group dicts.
        networks: A list of network dicts with UUID and fixed_ip.
        user_data: User data for instance.
        availability_zone: Availability zone in which to launch instance.
        accessIPv4: The IPv4 access address for the server.
        accessIPv6: The IPv6 access address for the server.
        min_count: Count of minimum number of instances to launch.
        max_count: Count of maximum number of instances to launch.
        disk_config: Determines if user or admin controls disk configuration.
        """
        server = Element("server",
                         xmlns=XMLNS_11,
                         imageRef=image_ref,
                         flavorRef=flavor_ref,
                         name=name)

        for attr in ["adminPass", "accessIPv4", "accessIPv6", "key_name"]:
            if attr in kwargs:
                server.add_attr(attr, kwargs[attr])

        if 'meta' in kwargs:
            metadata = Element("metadata")
            server.append(metadata)
            for k, v in kwargs['meta'].items():
                meta = Element("meta", key=k)
                meta.append(Text(v))
                metadata.append(meta)

        if 'personality' in kwargs:
            personality = Element('personality')
            server.append(personality)
            for k in kwargs['personality']:
                temp = Element('file', path=k['path'])
                temp.append(Text(k['contents']))
                personality.append(temp)

        resp, body = self.post('servers', str(Document(server)), self.headers)
        server = self._parse_server(etree.fromstring(body))
        return resp, server

    def wait_for_server_status(self, server_id, status):
        """Waits for a server to reach a given status"""
        resp, body = self.get_server(server_id)
        server_status = body['status']
        start = int(time.time())

        while(server_status != status):
            time.sleep(self.build_interval)
            resp, body = self.get_server(server_id)
            server_status = body['status']

            if server_status == 'ERROR':
                raise exceptions.BuildErrorException(server_id=server_id)

            timed_out = int(time.time()) - start >= self.build_timeout

            if server_status != status and timed_out:
                message = ('Server %s failed to reach %s status within the '
                           'required time (%s s).' %
                           (server_id, status, self.build_timeout))
                message += ' Current status: %s.' % server_status
                raise exceptions.TimeoutException(message)

    def wait_for_server_termination(self, server_id, ignore_error=False):
        """Waits for server to reach termination"""
        start_time = int(time.time())
        while True:
            try:
                resp, body = self.get_server(server_id)
            except exceptions.NotFound:
                return

            server_status = body['status']
            if server_status == 'ERROR' and not ignore_error:
                raise exceptions.BuildErrorException

            if int(time.time()) - start_time >= self.build_timeout:
                raise exceptions.TimeoutException

            time.sleep(self.build_interval)

    def _parse_network(self, node):
        addrs = []
        for child in node.getchildren():
            addrs.append({'version': int(child.get('version')),
                         'addr': child.get('version')})
        return {node.get('id'): addrs}

    def list_addresses(self, server_id):
        """Lists all addresses for a server"""
        resp, body = self.get("servers/%s/ips" % str(server_id), self.headers)

        networks = {}
        for child in etree.fromstring(body.getchildren()):
            network = self._parse_network(child)
            networks.update(**network)

        return resp, networks

    def list_addresses_by_network(self, server_id, network_id):
        """Lists all addresses of a specific network type for a server"""
        resp, body = self.get("servers/%s/ips/%s" % (str(server_id),
                                                     network_id),
                              self.headers)
        network = self._parse_network(etree.fromstring(body))

        return resp, network

    def change_password(self, server_id, password):
        cpw = Element("changePassword",
                      xmlns=XMLNS_11,
                      adminPass=password)
        return self.post("servers/%s/action" % server_id,
                         str(Document(cpw)), self.headers)

    def reboot(self, server_id, reboot_type):
        reboot = Element("reboot",
                         xmlns=XMLNS_11,
                         type=reboot_type)
        return self.post("servers/%s/action" % server_id,
                         str(Document(reboot)), self.headers)

    def rebuild(self, server_id, image_ref, name=None, meta=None,
                personality=None, adminPass=None, disk_config=None):
        rebuild = Element("rebuild",
                          xmlns=XMLNS_11,
                          imageRef=image_ref)

        if name:
            rebuild.add_attr("name", name)
        if adminPass:
            rebuild.add_attr("adminPass", adminPass)
        if meta:
            metadata = Element("metadata")
            rebuild.append(metadata)
            for k, v in meta.items():
                meta = Element("meta", key=k)
                meta.append(Text(v))
                metadata.append(meta)

        resp, body = self.post('servers/%s/action' % server_id,
                               str(Document(rebuild)), self.headers)
        server = self._parse_server(etree.fromstring(body))
        return resp, server

    def resize(self, server_id, flavor_ref, disk_config=None):
        resize = Element("resize",
                         xmlns=XMLNS_11,
                         flavorRef=flavor_ref)

        if disk_config is not None:
            raise Exception("Sorry, disk_config not supported via XML yet")

        return self.post('servers/%s/action' % server_id,
                         str(Document(resize)), self.headers)

    def confirm_resize(self, server_id):
        conf = Element('confirmResize')
        return self.post('servers/%s/action' % server_id,
                         str(Document(conf)), self.headers)

    def revert_resize(self, server_id):
        revert = Element('revertResize')
        return self.post('servers/%s/action' % server_id,
                         str(Document(revert)), self.headers)

    def create_image(self, server_id, image_name):
        metadata = Element('metadata')
        image = Element('createImage',
                        metadata,
                        xmlns=XMLNS_11,
                        name=image_name)
        return self.post('servers/%s/action' % server_id,
                         str(Document(image)), self.headers)

    def add_security_group(self, server_id, security_group_name):
        secgrp = Element('addSecurityGroup', name=security_group_name)
        return self.post('servers/%s/action' % server_id,
                         str(Document(secgrp)), self.headers)

    def remove_security_group(self, server_id, security_group_name):
        secgrp = Element('removeSecurityGroup', name=security_group_name)
        return self.post('servers/%s/action' % server_id,
                         str(Document(secgrp)), self.headers)
