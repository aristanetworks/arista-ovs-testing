
from nose.plugins.attrib import attr
from tempest import openstack
from tempest.common.utils.data_utils import rand_name
import unittest2 as unittest
from tempest import exceptions
from time import sleep

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

        cls.vEOS_ip = cls.config.network.vEOS_ip
        cls.vEOS_login = cls.config.network.vEOS_login
        cls.vEOS_pswd = cls.config.network.vEOS_pswd
        cls.vEOS_if = cls.config.network.vEOS_if

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

        #get test networks
        cls.tenant1_net1_id = cls.config.network.tenant1_net1_id
        cls.tenant1_net2_id = cls.config.network.tenant1_net2_id
        cls.tenant2_net1_id = cls.config.network.tenant2_net1_id

    def setUp(self):
        """Clean environment before a test is executed"""
        resp, body = self.servers_client.list_servers_with_detail()
        for serv in body['servers']:
            if str(serv['name']).find("tempest") != -1:
                resp, body = self.servers_client.delete_server(serv['id'])
                if resp['status'] == '204':
                    self.servers_client.delete_server(serv['id'])
                    self.servers_client.wait_for_server_termination(serv['id'],
                                                            ignore_error=True)

        resp, body = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        for net in body['networks']:
            if str(net['name']).find("tempest") != -1:
                resp, body = self.network_client.delete_network(net['id'])

    @attr(type='positive')
    def test_001_create_network(self):
        """Creates a network for a given tenant"""
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
        """Create instance providing net id"""
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
        host_name = server['OS-EXT-SRV-ATTR:host']
        net_info = server['addresses'].keys()
        self.assertEqual(str(network['name']), str(net_info[0]))
        #show openstack configuration in vEOS
        net_configuration = self._show_configuration_in_vEOS(
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
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")

    @attr(type='positive')
    def test_003_create_server_without_network(self):
        """Create instance without providing net id"""
        #create server without net
        server_name = rand_name('003-tempest-server-without-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref)
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.servers_client.get_server(body['id'])
        host_name = server['OS-EXT-SRV-ATTR:host']
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
            net_configuration = self._show_configuration_in_vEOS(
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
        """All network settings should remain after the instance reboot"""
        self.server1_t1n1_name = rand_name('004-tempest-tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        # get list of networks attached
        resp, server = self.servers_client.get_server(self.server1_t1n1_id)
        self.assertEqual('200', resp['status'])
        nets_attached1 = server['addresses'].keys()
        #reboot server
        res = self.servers_client.reboot(self.server1_t1n1_id, 'HARD')
        self.assertEqual(202, int(res[0]['status']))
        self.servers_client.wait_for_server_status( \
                                            self.server1_t1n1_id, 'ACTIVE')
        # get list of networks attached
        resp, server = self.servers_client.get_server(self.server1_t1n1_id)
        nets_attached2 = server['addresses'].keys()
        self.assertEqual(nets_attached1, nets_attached2, \
                         "All networks should remain after the server reboot")
        #get hostname of Compute host
        host_name = server['OS-EXT-SRV-ATTR:host']
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
            net_configuration = self._show_configuration_in_vEOS(
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
        self.servers_client.delete_server(self.server1_t1n1_id)

    @attr(type='negative')
    def test_005_l2_connectivity_diff_tenants(self):
        """Negative: Servers from different tenants
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
                                           self.vm_pswd)
        self.assertEqual(-1, serv_t2n1_available, \
                         "Server from tenant 2 should not be available via L2")
        serv_t1n1_available = self._check_l2_connectivity(self.server1_t2n1_ip,
                                           self.vm_login,
                                           self.vm_pswd)
        self.assertEqual(-1, serv_t1n1_available, \
                         "Server from tenant 1 should not be available via L2")
        self.servers_client.delete_server(self.server1_t1n1_id)
        self.servers_client.delete_server(self.server1_t2n1_id)

    @attr(type='negative')
    def test_006_l2_connectivity_diff_nets(self):
        """Negative: Servers from different networks within the same tenant
           should not have L2 connectivity"""
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
                                           self.vm_pswd)
        self.assertEqual(-1, serv_t1n2_available, \
            "Server from tenant1  network2 should not be available via L2")
        serv_t1n1_available = self._check_l2_connectivity(self.server1_t1n2_ip,
                                           self.vm_login,
                                           self.vm_pswd)
        self.assertEqual(-1, serv_t1n1_available, \
            "Server from tenant1  network1 should not be  available via L2")
        self.servers_client.delete_server(self.server1_t1n1_id)
        self.servers_client.delete_server(self.server1_t1n2_id)

    @attr(type='positive')
    def test_007_l2_connectivity_same_net(self):
        """Servers from the same network should have L2 connectivity"""
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
                                        self.vm_pswd)
        self.assertNotEqual(-1, serv2_t1n1_available, \
                "Server2 from the same network should be available via L2")
        serv1_t1n1_available = self._check_l2_connectivity(
                                        self.server2_t1n1_ip,
                                        self.vm_login,
                                        self.vm_pswd)
        self.assertNotEqual(-1, serv1_t1n1_available, \
                "Server1 from the same network should be available via L2")
        self.servers_client.delete_server(self.server1_t1n1_id)
        self.servers_client.delete_server(self.server2_t1n1_id)

    @attr(type='positive')
    def test_008_delete_unused_net(self):
        """Delete network that is not used"""
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
        net_configuration = self._show_configuration_in_vEOS(
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
               str(i).find(str(server['OS-EXT-SRV-ATTR:host'])) != -1:
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
        net_configuration = self._show_configuration_in_vEOS(
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
        """Negative: Deletion of network that is used should be prohibited"""
        self.server1_t1n1_name = rand_name('009-tenant1-net1-server1-')
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
        net_configuration = self._show_configuration_in_vEOS(self.vEOS_ip,
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
        """All network settings should remain after Quantum reboot"""
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
        host_name = server['OS-EXT-SRV-ATTR:host']
        #VLAN should be created in vEOS
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_configuration1 = self._show_configuration_in_vEOS(self.vEOS_ip,
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
        net_configuration2 = self._show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        self.assertEqual(net_configuration1, net_configuration2, \
                "All VLANs should remain after the Quantum reboot")
        self.servers_client.delete_server(self.server1_t1n2_id)

    @attr(type='positive')
    def test_011_delete_server(self):
        """Unused VLAN remains after the Server deletion"""
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
        #Network is unused now
        #network should be present in vEOS
        net_configuration = self._show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_present = False
        os_lines = str(net_configuration).splitlines()
        for i in os_lines:
            #if net id and hostname are found in the same string
            if str(i).find(network['id']) != -1 and \
               str(i).find(str(server['OS-EXT-SRV-ATTR:host'])) != -1:
                vlan_present = True
                break
        self.assertTrue(vlan_present)

    @attr(type='positive')
    def test_012_delete_server_VLAN_used_by_others(self):
        """VLAN in use remains after the Server deletion"""
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
        host1 = server1['OS-EXT-SRV-ATTR:host']
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
        host2 = server2['OS-EXT-SRV-ATTR:host']
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
            host3 = server3['OS-EXT-SRV-ATTR:host']
            resp, body = self.servers_client.delete_server(body3['id'])
            self.assertEqual('204', resp['status'])
            self.servers_client.wait_for_server_termination(body3['id'])
            #Network is unused now
            #network should be present in vEOS
            net_configuration = self._show_configuration_in_vEOS(
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
            net_configuration = self._show_configuration_in_vEOS(
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
    @unittest.skip("Until Keep-alive feature is implemented")
    def test_013_create_network_vEOS_down(self):
        """Network is created successfully when vEOS is down"""
        # Shut down vEOS - disconnect
        Popen("iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip,\
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
        Popen("iptables -D OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
        self.assertTrue(net_created)

    @attr(type='positive')
    @unittest.skip("Until Keep-alive feature is implemented")
    def test_014_delete_unused_net_vEOS_down(self):
        """Unused network can be deleted  when vEOS is down"""
        Popen("iptables -D OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
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
        net_configuration = self._show_configuration_in_vEOS(
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
               str(i).find(str(server['OS-EXT-SRV-ATTR:host'])) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created)
        resp, serv = self.servers_client.delete_server(body['id'])
        self.assertEqual('204', resp['status'])
        self.servers_client.wait_for_server_termination(body['id'])
        #Delete unused network
        # Shut down vEOS - disconnect
        Popen("iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
        #try to delete network
        try:
            resp, body = self.network_client.delete_network(network['id'])
        except:
            resp, networks = self.network_client.list_networks()
            deleted = False
            for net in  networks['networks']:
                if str(net).find(str(network['id'])) == -1:
                    deleted = True
                    break
            self.assertTrue(deleted)
        else:
            self.fail('Can not delete unused network when vEOS is down')
            Popen("iptables -D OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)

    @attr(type='negative')
    @unittest.skip("Until Keep-alive feature is implemented")
    def test_015_create_server_vEOS_down_no_VLAN(self):
        """Negative: can not create server when vEOS is down"""
        name = rand_name('015-tempest-network-')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        # Shut down vEOS - disconnect
        Popen("iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
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
    @unittest.skip("Until Keep-alive feature is implemented")
    def test_016_create_server_vEOS_down_VLAN_exists(self):
        """Create server when vEOS is down and required VLAN exists"""
        name = rand_name('016-tempest-network-')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        # Shut down vEOS - disconnect
        Popen("iptables -I OUTPUT -d %s/32 -j DROP" % self.vEOS_ip, \
                                        shell=True, stdout=PIPE)
        #
        #try to create server
        server_name = rand_name('016-tempest-server')
        server = self._create_test_server(server_name, self.image_ref,\
                                 self.image_ref, network['id'], False)
        resp, serv = self.servers_client.get_server(server[0])
        self.assertEqual('200', resp['status'])
        net = serv['addresses'].keys()
        self.assertEqual(str(network['name']), str(net[0]))

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

    def _show_configuration_in_vEOS(self, ip, username, password):
        """Utility that returns openstack configuration from vEOS"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username=username, password=password)
        # show network settings
        ssh.exec_command("en")
        proc = ssh.exec_command("show openstack")
        os_topology = proc[1].read()
        ssh.close()
        return os_topology

    def _check_l2_connectivity(self, ip, username, password):
        """Utility that returns the state of l2connectivity"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ping = Popen(["ping", "-c", "2", "-w", "1", ip],\
                                     shell=False, stdout=PIPE)
        ping.wait()
        if ping.returncode != 0:
            self.fail('Failed to ping host.')
        else:
            ssh.connect(ip, username=username, password=password)
        no_connection = "Received 0 reply (0 request(s), 0 broadcast(s))"
        # check network settings
        command = "sudo arping -c 3 " + ip + " | grep Received"
        output = ssh.exec_command(command)
        # Read the output
        bufferdata = output.stdout.read()
        if str(bufferdata).find(no_connection) != -1:
            found = 1
        else:
            found = -1
        ssh.close()
        return found


