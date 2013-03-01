from nose.plugins.attrib import attr
from tempest import openstack
from tempest.common.utils.data_utils import rand_name
import unittest2 as unittest
from tempest import exceptions
from time import sleep
import jsonrpclib
import os
import ConfigParser
import fabric.api
import fabric.context_managers

from paramiko import SSHClient
from paramiko import AutoAddPolicy

from subprocess import Popen, PIPE


class L2Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.os = openstack.Manager()
        #set up Network client
        cls.network_client = cls.os.network_client
        cls.config = cls.os.config

        #set up Alt Client
        cls.alt_manager = openstack.AltManager()
        cls.alt_servers_client = cls.alt_manager.servers_client
        cls.alt_network_client = cls.alt_manager.network_client
        cls.alt_security_client = cls.alt_manager.security_groups_client
        cls.alt_security_client._set_auth()

        #set up Server Client
        cls.servers_client = cls.os.servers_client
        cls.image_ref = cls.config.compute.image_ref
        cls.flavor_ref = cls.config.compute.flavor_ref
        cls.vm_login = cls.config.compute.ssh_user
        cls.vm_pswd = cls.config.compute.ssh_pswd
        cls.use_host_name = cls.config.compute.use_host_name

        #get test networks
        cls.tenant1_net1_id = cls.config.network.tenant1_net1_id
        cls.namespace1_1 = cls.config.network.namespace1_1
        cls.tenant1_net2_id = cls.config.network.tenant1_net2_id
        cls.namespace1_2 = cls.config.network.namespace1_2
        cls.tenant2_net1_id = cls.config.network.tenant2_net1_id
        cls.namespace2_1 = cls.config.network.namespace2_1

        #get "use_namespaces" parameter
        cls.dhcp_agent_ini = cls.config.network.dhcp_agent_ini
        cls.configure = ConfigParser.ConfigParser()
        cls.configure.read(cls.dhcp_agent_ini)
        cls.use_namespaces = cls.configure.getboolean("DEFAULT", "use_namespaces")

        #get vEOS access parameters
        cls.arista_driver_ini = cls.config.network.arista_driver_ini
        cls.configure = ConfigParser.ConfigParser()
        cls.configure.read(cls.arista_driver_ini)
        cls.vEOS_ip = cls.configure.get("ARISTA_DRIVER", "arista_eapi_host")
        cls.vEOS_login = cls.configure.get("ARISTA_DRIVER", "arista_eapi_user")
        cls.vEOS_pswd = cls.configure.get("ARISTA_DRIVER", "arista_eapi_pass")

        cls.url = 'https://' + cls.vEOS_login + ':' + cls.vEOS_pswd + '@' + \
                                cls.vEOS_ip + '/command-api'
        cls.server = jsonrpclib.Server(cls.url)

        cls.vEOS_is_apart = cls.config.network.vEOS_is_apart

        if cls.use_host_name == True:
            cls.hostname = 'OS-EXT-SRV-ATTR:host'
        else:
            cls.hostname = 'OS-EXT-SRV-ATTR:hypervisor_hostname'

    def setUp(self):
        """Clean environment before a test is executed"""
        with open(os.devnull, "w") as fnull:
            Popen("sudo iptables -D OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                    shell=True, stdout=fnull, stderr=fnull)
        resp, body = self.servers_client.list_servers_with_detail()
        #print body['servers']
        for serv in body['servers']:
            if str(serv['name']).find("tempest") != -1:
                resp, body = self.servers_client.delete_server(serv['id'])
                if resp['status'] == '204':
                    self.servers_client.delete_server(serv['id'])
                    self.servers_client.wait_for_server_termination(serv['id'],
                                                            ignore_error=True)
        resp, body = self.network_client.list_ports()
        self.assertEqual('200', resp['status'])
        for port in body['ports']:
            if str(port['name']).find("tempest") != -1:
                resp, body = self.network_client.delete_port(port['id'])
        resp, body = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        for net in body['networks']:
            if str(net['name']).find("tempest") != -1:
                resp, body = self.network_client.delete_network(net['id'])

    @attr(type='positive')
    def test_001_create_network(self):
        """001 - Creates a network for a given tenant"""
        #create net and check in Quantum
        name = rand_name('001-tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        resp, body = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_created = False
        for net in body['networks']:
            if str(net['id']).find(network['id']) != -1:
                net_created = True
                break
        self.assertTrue(net_created)

    @attr(type='positive')
    def test_002_create_server_with_network(self):
        """002 - Create instance providing net id"""
        #create net
        name = rand_name('002-tempest-network')
        resp, body = self.network_client.create_network(name)
        network = body['network']
        self.assertEqual('201', resp['status'])
        #create server
        server_name = rand_name('002-tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        host_name = server[self.hostname]
        net_info = server['addresses'].keys()
        self.assertEqual(str(network['name']), str(net_info[0]))
        #show openstack configuration in vEOS
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        # Read the output and check that VLAN for VM was created
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1 and \
               str(i).find(host_name) != -1:
                vlan_created = True
                vlan_info = str(i)
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")
        if not(self.vEOS_is_apart):
            #check if VLAN is up
            vlans = self._show_vlan_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
            vlan_lines = str(vlans).splitlines()
            vlan_up = False
            vlan_info_list = vlan_info.split(' ')
            vlan_list = list()
            for i in vlan_info_list:
                if str(i) != '':
                    vlan_list.append(i)
            vlan_id = vlan_list[2]
            for v in vlan_lines:
                if str(v).find(vlan_id) != -1 and \
                    str(v).find("active") != -1:
                    vlan_up = True
                    break
            self.assertTrue(vlan_up, "VLAN should be active in vEOS")

    @attr(type='positive')
    def test_003_create_server_without_network(self):
        """003 - Create instance without providing net id"""
        #create server without net
        server_name = rand_name('003-tempest-server-without-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref)
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.servers_client.get_server(body['id'])
        host_name = server[self.hostname]
        # get list of networks attached
        serv_nets_names = server['addresses'].keys()
        net_ids = []
        resp, networks = self.network_client.list_networks()
        for i in serv_nets_names:
            for net in  networks['networks']:
                if str(i).find(str(net.get('name'))) != -1:
                    net_ids.append(net.get('id'))
        if len(net_ids) != 0:
            #show openstack configuration in vEOS
            net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            number_vlan_created = 0
            os_lines = str(net_configuration).splitlines()
            for i in net_ids:
                for j in os_lines:
                    if str(j).find(str(i)) != -1 \
                     and str(j).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created, \
                             "All required VLANs should be created in vEOS")

    @attr(type='positive')
    def test_004_reboot_server(self):
        """004 - All network settings should remain after instance reboot"""
        name = rand_name('004-tempest-network-')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        server_name = rand_name('004-tempest-tenant1-net1-server1-')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        # get list of networks attached
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        nets_attached1 = server['addresses'].keys()
        #reboot server
        res = self.servers_client.reboot(body['id'], 'HARD')
        self.assertEqual(202, int(res[0]['status']))
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        # get list of networks attached
        resp, server = self.servers_client.get_server(body['id'])
        nets_attached2 = server['addresses'].keys()
        self.assertEqual(nets_attached1, nets_attached2, \
                         "All networks should remain after the server reboot")
        #get hostname of Compute host
        host_name = server[self.hostname]
        serv_nets_names = nets_attached2
        net_ids = []
        resp, networks = self.network_client.list_networks()
        for i in range(len(serv_nets_names)):
            for net in  networks['networks']:
                if str(serv_nets_names[i]).find(str(net.get('name'))) != -1:
                    net_ids.append(net.get('id'))
        # if some networks are attached to VM
        if len(net_ids) != 0:
            #show openstack configuration in vEOS
            net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            number_vlan_created = 0
            os_lines = str(net_configuration).splitlines()
            for i in os_lines:
                for j in net_ids:
                    if str(i).find(j) != -1 and \
                       str(i).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created, \
                    "All server VLANs should remain after the server reboot")

    @attr(type='negative')
    def test_005_l2_connectivity_diff_tenants(self):
        """005 - Negative: Servers from different tenants
           should not have L2 connectivity"""
        self.server1_t1n1_name = rand_name('005-tempest-tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        #test server from another tenant (network) - VM4
        self.server1_t2n1_name = rand_name('005-tempest-tenant2-net1-server1-')
        self.server1_t2n1_id, self.server1_t2n1_ip = self._create_test_server(
                                                   self.server1_t2n1_name,
                                                   self.image_ref,
                                                   self.flavor_ref,
                                                   self.tenant2_net1_id,
                                                   True)
        # check network settings
        serv_t2n1_available = self._check_l2_connectivity(self.server1_t1n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           self.server1_t2n1_ip,
                                           self.use_namespaces,
                                           self.namespace1_1)
        self.assertEqual(-1, serv_t2n1_available, \
                         "Server from tenant 2 should not be available via L2")
        serv_t1n1_available = self._check_l2_connectivity(self.server1_t2n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           self.server1_t1n1_ip,
                                           self.use_namespaces,
                                           self.namespace2_1)
        self.assertEqual(-1, serv_t1n1_available, \
                         "Server from tenant 1 should not be available via L2")
        self.servers_client.delete_server(self.server1_t2n1_id)

    @attr(type='negative')
    def test_006_l2_connectivity_diff_nets(self):
        """006 - Negative: Servers from different networks within the same
           tenant should not have L2 connectivity"""
        self.server1_t1n1_name = rand_name('006-tempest-tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        # test server in the same tenant, another network
        self.server1_t1n2_name = rand_name('006-tempest-tenant1-net2-server1-')
        self.server1_t1n2_id, self.server1_t1n2_ip = self._create_test_server(
                                                    self.server1_t1n2_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net2_id,
                                                    False)
        # check network settings
        serv_t1n2_available = self._check_l2_connectivity(self.server1_t1n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           self.server1_t1n2_ip,
                                           self.use_namespaces,
                                           self.namespace1_1)
        self.assertEqual(-1, serv_t1n2_available, \
            "Server from tenant1  network2 should not be available via L2")
        serv_t1n1_available = self._check_l2_connectivity(self.server1_t1n2_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           self.server1_t1n1_ip,
                                           self.use_namespaces,
                                           self.namespace1_2)
        self.assertEqual(-1, serv_t1n1_available, \
            "Server from tenant1  network1 should not be  available via L2")

    @attr(type='positive')
    def test_007_l2_connectivity_same_net(self):
        """007 - Servers from the same network should have L2 connectivity"""
        self.server1_t1n1_name = rand_name('007-tempest-tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        self.server2_t1n1_name = rand_name('007-tempest-tenant1-net1-server2-')
        self.server2_t1n1_id, self.server2_t1n1_ip = self._create_test_server(
                                                    self.server2_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        # check network settings
        serv2_t1n1_available = self._check_l2_connectivity(
                                        self.server1_t1n1_ip,
                                        self.vm_login,
                                        self.vm_pswd,
                                        self.server2_t1n1_ip,
                                        self.use_namespaces,
                                        self.namespace1_1)
        self.assertNotEqual(-1, serv2_t1n1_available, \
                "Server2 from the same network should be available via L2")
        serv1_t1n1_available = self._check_l2_connectivity(
                                        self.server2_t1n1_ip,
                                        self.vm_login,
                                        self.vm_pswd,
                                        self.server1_t1n1_ip,
                                        self.use_namespaces,
                                        self.namespace1_1)
        self.assertNotEqual(-1, serv1_t1n1_available, \
                "Server1 from the same network should be available via L2")

    @attr(type='positive')
    def test_008_delete_unused_net(self):
        """008 - Delete network that is not used"""
        name = rand_name('008-tempest-network-')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        #boot server - VLAN should be created in vEOS
        server_name = rand_name('008-tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #Network is used now
        #network should be present in vEOS
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1 and \
               str(i).find(str(server[self.hostname])) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created)
        resp, serv = self.servers_client.delete_server(body['id'])
        self.assertEqual('204', resp['status'])
        self.servers_client.wait_for_server_termination(body['id'])
        #Delete unused network
        resp, body = self.network_client.delete_network(network['id'])
        self.assertEqual('204', resp['status'])
        #network should be removed from vEOS
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_deleted = True
        os_lines = str(net_configuration).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1:
                vlan_deleted = False
                break
        self.assertTrue(vlan_deleted, \
                         "Unused VLAN should be deleted from vEOS")
        resp, body = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_deleted = True
        for net in body['networks']:
            if str(net['id']).find(network['id']) != -1:
                net_deleted = False
                break
        self.assertTrue(net_deleted)

    @attr(type='negative')
    def test_009_delete_net_in_use(self):
        """009 - Negative: Deletion of network that is used should be prohibited"""
        self.server1_t1n1_name = rand_name('009-tempest-tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        try:
            self.network_client.delete_network(self.tenant1_net1_id)
        except exceptions.Duplicate:
            pass
        else:
            self.fail('Deletion of network'\
                      ' that is used should be prohibited')
        net_configuration = self._show_openstack_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        # Read the output and check that network for VM was not deleted
        vlan_present = False
        os_lines = str(net_configuration).splitlines()
        for i in range(len(os_lines)):
            #if net id and hostname are found in the same string
            if str(os_lines[i]).find(self.tenant1_net1_id) != -1:
                vlan_present = True
                break
        self.assertTrue(vlan_present, "VLAN should not be deleted from vEOS")
        self.servers_client.delete_server(self.server1_t1n1_id)
        self.servers_client.wait_for_server_termination(self.server1_t1n1_id)
        resp, body = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_present = False
        for net in body['networks']:
            if str(net['id']).find(self.tenant1_net1_id) != -1:
                net_present = True
                break
        self.assertTrue(net_present)

    @attr(type='positive')
    def test_010_reboot_Quantum(self):
        """010 - All network settings should remain after Quantum reboot"""
        # create instance to add VLAN to vEOS
        self.server1_t1n2_name = rand_name('010-tempest-tenant1-net1-server1-')
        self.server1_t1n2_id, self.server1_t1n2_ip = self._create_test_server(
                                                    self.server1_t1n2_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net2_id,
                                                    False)
        resp, server = self.servers_client.get_server(self.server1_t1n2_id)
        self.assertEqual('200', resp['status'])
        host_name = server[self.hostname]
        #VLAN should be created in vEOS
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_configuration1 = self._show_openstack_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration1).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(self.tenant1_net2_id) != -1 and \
               str(i).find(host_name) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")
        #Reboot Quantum
        Popen('sh /usr/sbin/quantum-restart.sh', shell=True, stdout=PIPE)
        sleep(5)
        #check network settings after reboot
        resp, body2 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        self.assertEqual(body1, body2, \
                "All networks should remain after the Quantum reboot")
        net_configuration2 = self._show_openstack_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        self.assertEqual(net_configuration1, net_configuration2, \
                "All VLANs should remain after the Quantum reboot")

    @attr(type='positive')
    def test_011_delete_server(self):
        """011 - Unused VLAN remains after the Server deletion"""
        name = rand_name('011-tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        #boot server - VLAN should be created in vEOS
        server_name = rand_name('011-tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        self.servers_client.delete_server(body['id'])
        self.servers_client.wait_for_server_termination(body['id'])
        #Network is unused now
        #network should be present in vEOS
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_present = False
        os_lines = str(net_configuration).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1 and \
               str(i).find(str(server[self.hostname])) != -1:
                vlan_present = True
                break
        self.assertTrue(vlan_present)

    @attr(type='positive')
    def test_012_delete_server_VLAN_used_by_others(self):
        """012 - VLAN in use remains after the Server deletion"""
        name = rand_name('012-tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        #boot server - VLAN should be created in vEOS
        server_name = rand_name('012-tempest-server1-')
        resp1, body1 = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp1['status'])
        self.servers_client.wait_for_server_status(body1['id'], 'ACTIVE')
        resp1, server1 = self.servers_client.get_server(body1['id'])
        self.assertEqual('200', resp1['status'])
        host1 = server1[self.hostname]
        # boot VM2
        server_name = rand_name('012-tempest-server2-')
        resp2, body2 = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp2['status'])
        self.servers_client.wait_for_server_status(body2['id'], 'ACTIVE')
        resp2, server2 = self.servers_client.get_server(body2['id'])
        self.assertEqual('200', resp2['status'])
        host2 = server2[self.hostname]
        if str(host1) != str(host2):
            # boot VM3
            server_name = rand_name('012-tempest-server3-')
            resp3, body3 = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
            self.assertEqual('202', resp3['status'])
            self.servers_client.wait_for_server_status(body3['id'], 'ACTIVE')
            resp3, server3 = self.servers_client.get_server(body3['id'])
            self.assertEqual('200', resp3['status'])
            host3 = server3[self.hostname]
            resp, body = self.servers_client.delete_server(body3['id'])
            self.assertEqual('204', resp['status'])
            self.servers_client.wait_for_server_termination(body3['id'])
            #Network is unused now
            #network should be present in vEOS
            net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            vlan_present = False
            os_lines = str(net_configuration).splitlines()
            for i in os_lines:
                #if net id and hostname are found in the same string
                if str(i).find(network['id']) != -1 and \
                str(i).find(str(host3)) != -1:
                    vlan_present = True
                    break
            self.assertTrue(vlan_present)
        else:
            resp, body = self.servers_client.delete_server(body1['id'])
            self.assertEqual('204', resp['status'])
            self.servers_client.wait_for_server_termination(body1['id'])
            #Network is unused now
            #network should be present in vEOS
            net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            vlan_present = False
            os_lines = str(net_configuration).splitlines()
            for i in os_lines:
                #if net id and hostname are found in the same string
                if str(i).find(network['id']) != -1 and \
                str(i).find(str(host1)) != -1:
                    vlan_present = True
                    break
            self.assertTrue(vlan_present)

    @attr(type='positive')
    def test_013_vEOS_sync_with_new_networks(self):
        """013 - No new tenant-networks in vEOS after sync"""
        # Shut down vEOS - disconnect
        Popen("sudo iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip,\
                                        shell=True, stdout=PIPE)
        #try to create network
        name = rand_name('013-tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        resp, body = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_created = False
        for net in body['networks']:
            if str(net['id']).find(network['id']) != -1:
                net_created = True
                break
        self.assertTrue(net_created)
        #network should not be present in vEOS
        Popen("sudo iptables -D OUTPUT -d %s/32 -j DROP" % self.vEOS_ip,\
                                        shell=True, stdout=PIPE)
        # wait for at least one sync interval
        sleep(15)
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1:
                vlan_created = True
                break
        self.assertFalse(vlan_created)

    @attr(type='positive')
    def test_014_vEOS_sync_with_deleted_nets(self):
        """014 - Unused network will be deleted  after vEOS sync"""
        name = rand_name('014-tempest-network-')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        #boot server - VLAN should be created in vEOS
        server_name = rand_name('014-tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #Network is used now
        #network should be present in vEOS
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1 and \
               str(i).find(str(server[self.hostname])) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created)
        resp, serv = self.servers_client.delete_server(body['id'])
        self.assertEqual('204', resp['status'])
        self.servers_client.wait_for_server_termination(body['id'])
        #Delete unused network
        # Shut down vEOS - disconnect
        Popen("sudo iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
        #try to delete network
        try:
            resp, body = self.network_client.delete_network(network['id'])
        except:
            pass
        else:
            Popen("sudo iptables -D OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
            # wait for at least one sync interval
            sleep(15)
            resp, networks = self.network_client.list_networks()
            deleted = True
            for net in  networks['networks']:
                if str(net).find(str(network['id'])) != -1:
                    deleted = False
                    break
            self.assertTrue(deleted)
            #VLAN should be deleted in vEOS
            net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            vlan_deleted = True
            os_lines = str(net_configuration).splitlines()
            for i in os_lines:
            #if net id and hostname are found in the same string
                if str(i).find(network['id']) != -1:
                    vlan_deleted = False
                    break
            self.assertTrue(vlan_deleted)

    @attr(type='positive')
    def test_015_create_server_vEOS_down_VLAN_exists(self):
        """015 - Create server when vEOS is down and required VLAN exists"""
        # Shut down vEOS - disconnect
        Popen("sudo iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
        #
        #try to create server
        server_name = rand_name('016-tempest-server')
        server = self._create_test_server(server_name, self.image_ref,\
                                 self.flavor_ref, self.tenant1_net1_id, False)
        resp, serv = self.servers_client.get_server(server[0])
        self.assertEqual('200', resp['status'])

    @attr(type='negative')
    def test_016_create_server_vEOS_down_no_VLAN(self):
        """016 - Negative: can not create server when vEOS is down"""
        name = rand_name('015-tempest-network-')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        # Shut down vEOS - disconnect
        Popen("sudo iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
        #
        #try to create server
        name = rand_name('015-tempest-server')
        try:
            resp, body = self.servers_client.create_server(name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
            self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        except exceptions.BuildErrorException:
            pass
        else:
            self.fail('Can not create server when vEOS is down')
        resp, serv = self.servers_client.get_server(body['id'])
        self.assertEqual(0, len(serv['addresses']), \
                         "No nets  should be assigned")
        self.servers_client.wait_for_server_status(body['id'], 'ERROR')

    @attr(type='positive')
    def test_017_vEOS_sync_with_new_assigned_networks(self):
        """017 - vEOS should set up VLANs according to Quantum DB"""
        #create net
        name = rand_name('017-tempest-network')
        resp, body = self.network_client.create_network(name)
        network = body['network']
        self.assertEqual('201', resp['status'])
        #create server
        server_name = rand_name('017-tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute hostquantum net-list
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        host_name = server[self.hostname]
        net_info = server['addresses'].keys()
        self.assertEqual(str(network['name']), str(net_info[0]))
        self.server.runCmds(cmds=['configure', \
                                 'management openstack', \
                                 'no tenant-network %s' % network['id'], \
                                 'exit'])
        #show openstack configuration in vEOS
        sleep(15)
        net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        # Read the output and check that VLAN for VM was created
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1 and \
               str(i).find(host_name) != -1:
                vlan_created = True
                vlan_info = str(i)
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")
        if not(self.vEOS_is_apart):
            #check if VLAN is up
            vlans = self._show_vlan_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
            vlan_lines = str(vlans).splitlines()
            vlan_up = False
            vlan_info_list = vlan_info.split(' ')
            vlan_list = list()
            for i in vlan_info_list:
                if str(i) != '':
                    vlan_list.append(i)
            vlan_id = vlan_list[2]
            for v in vlan_lines:
                if str(v).find(vlan_id) != -1 and \
                    str(v).find("active") != -1:
                    vlan_up = True
                    break
            self.assertTrue(vlan_up, "VLAN should be active in vEOS")

    @attr(type='positive')
    def test_018_create_server_with_net_via_port(self):
        """018 - Creates a server with network via port instantiation"""
        #create net and check in Quantum
        name = rand_name('0018-tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        port_name = rand_name('018-tempest-port')
        resp, body = self.network_client.create_port(port_name, network['id'])
        port = body['port']
        self.assertEqual('201', resp['status'])
        server_name = rand_name('018-tempest-server-')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 port=port['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.servers_client.get_server(body['id'])
        host_name = server[self.hostname]
        # get list of networks attached
        serv_nets_names = server['addresses'].keys()
        net_ids = []
        resp, networks = self.network_client.list_networks()
        for i in serv_nets_names:
            for net in  networks['networks']:
                if str(i).find(str(net.get('name'))) != -1:
                    net_ids.append(net.get('id'))
        if len(net_ids) != 0:
            #show openstack configuration in vEOS
            net_configuration = self._show_openstack_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            number_vlan_created = 0
            os_lines = str(net_configuration).splitlines()
            for i in net_ids:
                for j in os_lines:
                    if str(j).find(str(i)) != -1 \
                     and str(j).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created, \
                             "All required VLANs should be created in vEOS")

    def _create_test_server(self, server_name, image_ref,\
                             flavor_ref, net_id, alt_client):
        """Utility that returns a test server"""
        if alt_client == True:
            resp, body = self.alt_servers_client.create_server(server_name,
                                                       image_ref,
                                                       flavor_ref,
                                                       networks=net_id)
        else:
            resp, body = self.servers_client.create_server(server_name,
                                                       image_ref,
                                                       flavor_ref,
                                                       networks=net_id)
        server_id = body['id']
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        resp, body = self.servers_client.get_server(body['id'],)
        self.assertEqual('200', resp['status'])
        network_attached = body['addresses'].popitem()
        ip = network_attached[1]
        server_ip = ip[0].get('addr')
        return server_id, server_ip

    def _show_openstack_in_vEOS(self, ip, username, password):
        """Utility that returns openstack configuration from vEOS"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username=username, password=password)
        # show network settings
        proc = ssh.exec_command("show openstack")
        os_topology = proc[1].read()
        ssh.close()
        return os_topology

    def _show_vlan_in_vEOS(self, ip, username, password):
        """Utility that returns openstack configuration from vEOS"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username=username, password=password)
        # show network settings
        proc = ssh.exec_command("show vlan")
        os_topology = proc[1].read()
        ssh.close()
        return os_topology

    def _check_l2_connectivity(self, ip, username, password, to_ip,
                                     use_namespaces, namespace):
        if use_namespaces:
            custom = CustomLab(ip, to_ip)
            found = custom.check_l2_connectivity(username, password, namespace)
        else:
            local = LocalLab(ip, to_ip)
            found = local.check_l2_connectivity(username, password)
        return found


class BaseLab(unittest.TestCase):
    def __init__(self, ip_src, ip_dst):
        self.ip = ip_src
        self.to_ip = ip_dst


class LocalLab(BaseLab):
    def check_l2_connectivity(self, username, password):
        """Utility that returns the state of l2connectivity"""
        found = 0
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ping = Popen(["ping", "-c", "300", self.ip], \
                                     shell=False, stdout=PIPE)
        ping.wait()
        if ping.returncode != 0:
            self.fail('Failed to ping host')
        else:
            ssh.connect(self.ip, username=username, password=password)
            no_connection = "Received 0 reply (0 request(s), 0 broadcast(s))"
            # check network settings
            command = "sudo arping -c 20 " + self.to_ip
            # + " | grep Received"
            output = ssh.exec_command(command)
            # Read the output
            bufferdata = output[1].read()
            if str(bufferdata).find(no_connection) != -1:
                found = -1
            else:
                found = 1
        ssh.close()
        return found


class CustomLab(BaseLab):

    def check_l2_connectivity_fabric(self, username, password, namespace):
        """Utility that returns the state of l2connectivity"""
        found = 0
        #prepare fabric
        #with fabric.context_managers.prefix('source ' + self.env_path):
        result = fabric.api.run('ip netns exec %s ping -c 300 %s' \
                                     % namespace % self.ip)
        if str(result).find("0% packet loss"):
            output = fabric.api.run('ip netns exec %s ssh -f %s@%s -P %s; sudo arping -c 20 %s' \
                    % namespace % username % self.ip % password % self.to_ip)
            no_connection = "Received 0 reply (0 request(s), 0 broadcast(s))"
            if str(output).find(no_connection) != -1:
                found = -1
            else:
                found = 1
        else:
            self.fail('Failed to ping host.')
        return found
