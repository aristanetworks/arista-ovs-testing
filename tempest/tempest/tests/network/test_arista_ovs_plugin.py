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
        Popen("iptables -I INPUT -s %s -j ACCEPT" % self.vEOS_ip, shell=True)

    @attr(type='demo')
    def test_001_create_network(self):
        """Creates a network for a given tenant"""
        #create net and check in Quantum
        name = rand_name('tempest-network')
        res = self.network_client.create_network(name)
        self.assertEqual('201', res[0]['status'])

    @attr(type='demo')
    def test_002_create_server_with_network(self):
        """Create instance providing net id"""
        server_name = rand_name('tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=self.tenant1_net1_id)
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.servers_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        host_name = server['OS-EXT-SRV-ATTR:host']
        #show openstack configuration in vEOS
        net_configuration = self._show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        # Read the output and check that VLAN for VM was created
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        for i in range(len(os_lines)):
            #if net id and hostname are found in the same string
            if str(os_lines[i]).find(self.tenant1_net1_id) != -1 \
            and str(os_lines[i]).find(host_name) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")

    @attr(type='demo')
    def test_003_create_server_without_network(self):
        """Create instance without providing net id"""
        #create server without net
        server_name = rand_name('tempest-server-without-net')
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
        for i in range(len(serv_nets_names)):
            for net in  networks['networks']:
                if str(serv_nets_names[i]).find(str(net.get('name'))) != -1:
                    net_ids.append(net.get('id'))
        if len(net_ids) != 0:
            #show openstack configuration in vEOS
            net_configuration = self._show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            number_vlan_created = 0
            os_lines = str(net_configuration).splitlines()
            for i in range(len(os_lines)):
                for j in range(len(net_ids)):
                    if str(os_lines[i]).find(str(j)) != -1 \
                     and str(os_lines[i]).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created, \
                             "All required VLANs should be created in vEOS")

    @attr(type='demo')
    def test_004_reboot_server(self):
        """All network settings should remain after the instance reboot"""
        self.server1_t1n1_name = rand_name('tenant1-net1-server1-')
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
            for i in range(len(os_lines)):
                for i in range(len(net_ids)):
                    if str(os_lines[i]).find(net_ids[i]) != -1 \
                    and str(os_lines[i]).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created, \
                    "All server VLANs should remain after the server reboot")
        self.servers_client.delete_server(self.server1_t1n1_id)

    @attr(type='negative')
    def test_005_l2_connectivity_diff_tenants(self):
        """Negative: Servers from different tenants
           should not have L2 connectivity"""
        self.server1_t1n1_name = rand_name('tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        #test server from another tenant (network) - VM4
        self.server1_t2n1_name = rand_name('tenant2-net1-server1-')
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
        self.server1_t1n1_name = rand_name('tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        # test server in the same tenant, another network
        self.server1_t1n2_name = rand_name('tenant1-net2-server1-')
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
        self.server1_t1n1_name = rand_name('tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        self.server2_t1n1_name = rand_name('tenant1-net1-server2-')
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

    @attr(type='demo')
    def test_008_delete_unused_net(self):
        """Delete network that is not used"""
        name = rand_name('tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        #boot server - VLAN should be created in vEOS
        server_name = rand_name('tempest-server-with-net')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=network['id'])
        self.assertEqual('202', resp['status'])
        self.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        self.servers_client.delete_server(body['id'])
        #Network is unused now
        #network should be present in vEOS
        net_configuration = self._show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration).splitlines()
        for i in range(len(os_lines)):
            #if net id and hostname are found in the same string
            if str(os_lines[i]).find(network['id']) != -1 \
                and str(os_lines[i]).find(body['OS-EXT-SRV-ATTR:host']) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created)
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
        for i in range(len(os_lines)):
            #if net id and hostname are found in the same string
            if str(os_lines[i]).find(network['id']) != -1:
                vlan_deleted = False
                break
        self.assertTrue(vlan_deleted, \
                         "Unused VLAN should be deleted from vEOS")

    @attr(type='demo')
    def test_009_delete_net_in_use(self):
        """Negative: Deletion of network that is used should be prohibited"""
        self.server1_t1n1_name = rand_name('tenant1-net1-server1-')
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

    @attr(type='demo')
    def test_010_reboot_vEOS(self):
        """All network settings should remain after vEOS reboot"""
        # create instance to add VLAN to vEOS
        self.server1_t1n1_name = rand_name('tenant1-net1-server1-')
        self.server1_t1n1_id, self.server1_t1n1_ip = self._create_test_server(
                                                    self.server1_t1n1_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net1_id,
                                                    False)
        resp, server = self.servers_client.get_server(self.server1_t1n1_id)
        self.assertEqual('200', resp['status'])
        host_name = server['OS-EXT-SRV-ATTR:host']
        #Network should be created in vEOS
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_configuration1 = self._show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration1).splitlines()
        for i in range(len(os_lines)):
            #if net id and hostname are found in the same string
            if str(os_lines[i]).find(self.tenant1_net1_id) != -1 \
                and str(os_lines[i]).find(host_name) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")
        #Reboot vEOS
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip, username=self.vEOS_login,\
                                     password=self.vEOS_pswd)
        ssh.exec_command("init 6")
        ssh.close()
        #check network settings after reboot
        resp, body2 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        self.assertEqual(body1, body2, \
                "All networks should remain after the vEOS reboot")
        net_configuration2 = self._show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        self.assertEqual(net_configuration1, net_configuration2, \
                         "All VLANs should remain after the vEOS reboot")
        self.servers_client.delete_server(self.server1_t1n1_id)

    @attr(type='demo')
    def test_011_reboot_Quantum(self):
        """All network settings should remain after Quantum reboot"""
        # create instance to add VLAN to vEOS
        self.server1_t1n2_name = rand_name('tenant1-net1-server1-')
        self.server1_t1n2_id, self.server1_t1n2_ip = self._create_test_server(
                                                    self.server1_t1n2_name,
                                                    self.image_ref,
                                                    self.flavor_ref,
                                                    self.tenant1_net2_id,
                                                    False)
        resp, server = self.servers_client.get_server(self.server1_t1n2_id)
        self.assertEqual('200', resp['status'])
        host_name = server['OS-EXT-SRV-ATTR:host']
        #Network should be created in vEOS
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        net_configuration1 = self._show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        vlan_created = False
        os_lines = str(net_configuration1).splitlines()
        for i in range(len(os_lines)):
            #if net id and hostname are found in the same string
            if str(os_lines[i]).find(self.tenant1_net2_id) != -1 \
                and str(os_lines[i]).find(host_name) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created, "VLAN should be created in vEOS")
        #Reboot Quantum
        Popen(['/etc/init.d/quantum-server', 'restart'], stdout=PIPE)
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

    @attr(type='negative')
    def test_012_create_network_vEOS_down(self):
        """Negative: can not create network when vEOS is down"""
        # Shut down vEOS - disconnect
        Popen("iptables -I INPUT -s %s -j DROP" % self.vEOS_ip, shell=True)
        #try to create network
        name = rand_name('tempest-network')
        res = self.network_client.create_network(name)
        self.assertEqual('400', res[0]['status'])

    @attr(type='negative')
    def test_013_delete_unused_net_vEOS_down(self):
        """Negative: can not delete unused network when vEOS is down"""
        name = rand_name('tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        # Shut down vEOS - disconnect
        Popen("iptables -I INPUT -s %s -j DROP" % self.vEOS_ip, shell=True)
        #try to delete network
        resp, body = self.network_client.delete_network(network['id'])
        self.assertEqual('404', int(resp['status']))

    @attr(type='negative')
    def test_014_create_server_vEOS_down(self):
        """Negative: can not create server when vEOS is down"""
        # Shut down vEOS - disconnect
        Popen("iptables -I INPUT -s %s -j DROP" % self.vEOS_ip, shell=True)
        #
        #try to create server
        name = rand_name('tempest-server')
        try:
            self.servers_client.create_server(name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=self.tenant1_net2_id)
        except exceptions.NotFound:
            pass
        else:
            self.fail('Server can not be created when vEOS is down')

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

    def _get_MAC_addr_of_server(self, ip, username, password):
        """Utility that returns MAC-address for server"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username=username, password=password)
        #Get MAC address
        output = ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output
        data = output.stdout.read()
        HWaddr = str(data)[str(data).find("HWaddr"):len(str(data))]
        HWaddr = str(HWaddr).strip()
        ssh.close()
        return HWaddr

    def _check_l2_connectivity(self, ip, username, password):
        """Utility that returns the state of l2connectivity"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
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

