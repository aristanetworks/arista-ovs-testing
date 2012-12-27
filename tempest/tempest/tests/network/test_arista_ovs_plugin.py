from nose.plugins.attrib import attr
from tempest import openstack
from tempest.common.utils.data_utils import rand_name
from tempest.tests.network import base


from paramiko import SSHClient
from paramiko import AutoAddPolicy

from subprocess import Popen


class L2Test(object):

    @classmethod
    def setUpClass(cls):        
        cls.os = openstack.Manager()
        #set up Network client
        cls.network_client = cls.os.network_client
        cls.config = cls.os.config

        cls.vEOS_ip = '172.0.0.0'
        cls.vEOS_login = 'admin'
        cls.vEOS_pswd = 'r00tme'
        cls.vEOS_if = 'br100'

        #set up Admin Client
        cls.admin_client = cls.os.admin_client

        #set up Server Client
        cls.servers_client = cls.os.servers_client
        cls.image_ref = cls.config.compute.image_ref
        cls.flavor_ref = cls.config.compute.flavor_ref
        cls.vm_login = cls.config.compute.ssh_user
        cls.vm_pswd = cls.config.compute.ssh_password

        #get test networks
        cls.tenant1_net1_id = cls.config.network.tenant1_net1_id
        cls.tenant1_net2_id = cls.config.network.tenant1_net2_id
        cls.tenant2_net1_id = cls.config.network.tenant2_net1_id

        # two test servers within one network same tenant
        cls.server1_t1n1_name = rand_name('tenant1-net1-server1-')
        cls.server1_t1n1_id, cls.server1_t1n1_ip = cls.create_test_server(
                                                    cls.server1_t1n1_name,
                                                    cls.image_ref,
                                                    cls.flavor_ref,
                                                    cls.tenant1_net1_id)
        cls.server2_t1n1_name = rand_name('tenant1-net1-server2-')
        cls.server2_t1n1_id, cls.server2_t1n1_ip = cls.create_test_server(
                                                    cls.server2_t1n1_name,
                                                    cls.image_ref,
                                                    cls.flavor_ref,
                                                    cls.tenant1_net1_id)
        # test server in the same tenant, another network
        cls.server1_t1n2_name = rand_name('tenant1-net2-server1-')
        cls.server1_t1n2_id, cls.server1_t1n2_ip = cls.create_test_server(
                                                    cls.server1_t1n2_name,
                                                    cls.image_ref,
                                                    cls.flavor_ref,
                                                    cls.tenant1_net2_id)
        # test server from another tenant (network) - VM4
        cls.server1_t2n1_name = rand_name('tenant2-net1-server1-')
        cls.server1_t2n1_id, cls.server1_t2n1_ip = cls.create_test_server(
                                                    cls.server1_t2n1_name,
                                                    cls.image_ref,
                                                    cls.flavor_ref,
                                                    cls.tenant2_net_id)

    @attr(type='positive')
    def test_create_network(self):
        """Creates a network for a tenant"""
        #create net and check in Quantum
        name = rand_name('tempest-network')
        res = self.network_client.create_network(name)
        self.assertEqual('201', res.resp['status'])

    @attr(type='positive')
    def test_create_server_with_network(self):
        """Create instance providing net id"""
        server_name = rand_name('tempest-server')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks=self.tenant1_net1_id)
        self.assertEqual('202', resp['status'])
        self.client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.server_client.get_server(body['id'])
        self.assertEqual('200', resp['status'])
        host_name = server['host']
        #show openstack configuration in vEOS
        net_configuration = self.show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
        # Read the output and check that VLAN for VM was created
        vlan_created = False
        for line in iter(net_configuration.stdout.readline, ''):
            #if net id and hostname are found in the same string
            if str(line).find(self.tenant1_net1_id) != -1 and str(line).find(host_name) != -1:
                vlan_created = True
                break
        self.assertTrue(vlan_created)

    @attr(type='positive')
    def test_create_server_without_network(self):
        """Create instance without providing net id"""
        #create server without net
        server_name = rand_name('tempest-server')
        resp, body = self.servers_client.create_server(server_name,
                                                 self.image_ref,
                                                 self.flavor_ref)
        self.assertEqual('202', resp['status'])
        self.client.wait_for_server_status(body['id'], 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.server_client.get_server(body['id'])
        host_name = server['host']
        # get list of networks attached
        networks_attached_names = server['addresses'].keys()
        net_ids = []
        resp, networks = self.network_client.list_networks()
        for i in range(len(networks_attached_names)):
            for net in  networks['networks']:
                if str(networks_attached_names[i]).find(str(net.get('name'))) != -1:
                    net_ids.append(net.get('id'))
        # if some networks are attached to VM
        if len(net_ids) != 0:
            #show openstack configuration in vEOS
            net_configuration = self.show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            number_vlan_created = 0
            for line in iter(net_configuration.stdout.readline, ''):
                for i in range(len(net_ids)):
                    if str(line).find(str(i)) != -1 and str(line).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created)

    @attr(type='positive')
    def test_reboot_server(self):
        """All network settings should remain after the instance reboot"""
        # get list of networks attached
        resp, server = self.servers_client.get_server(self.server1_id)
        self.assertEqual('200', resp['status'])
        nets_attached1 = server['addresses'].keys()
        #reboot server
        res = self.client.reboot(self.server1_id, 'HARD')
        self.assertEqual(202, res.resp.status)
        self.client.wait_for_server_status(self.server1_id, 'ACTIVE')
        # get list of networks attached
        resp, server = self.servers_client.get_server(self.server1_id)
        nets_attached2 = server['addresses'].keys()
        self.assertEqual(nets_attached1, nets_attached2)
        #get hostname of Compute host
        host_name = server['host']
        networks_attached_names = nets_attached2
        net_ids = []
        resp, networks = self.network_client.list_networks()
        for i in range(len(networks_attached_names)):
            for net in  networks['networks']:
                if str(networks_attached_names[i]).find(str(net.get('name'))) != -1:
                    net_ids.append(net.get('id'))
        # if some networks are attached to VM
        if len(net_ids) != 0:
            #show openstack configuration in vEOS
            net_configuration = self.show_configuration_in_vEOS(
                                                self.vEOS_ip,
                                                self.vEOS_login,
                                                self.vEOS_pswd)
            number_vlan_created = 0
            for line in iter(net_configuration.stdout.readline, ''):
                for i in range(len(net_ids)):
                    if str(line).find(net_ids[i]) != -1 and str(line).find(host_name) != -1:
                        number_vlan_created = number_vlan_created + 1
            self.assertEqual(len(net_ids), number_vlan_created)

    @attr(type='negative')
    def test_l2_connectivity_diff_tenants(self):
        """Negative: Servers from different tenants
           should not have L2 connectivity"""
        HWaddr_server_t1n1 = self.get_MAC_addr_of_server(self.server1_t1n1_ip,
                                                            self.vm_login,
                                                            self.vm_pswd)
        HWaddr_server_t2n1 = self.get_MAC_addr_of_server(self.server1_t2n1_ip,
                                                            self.vm_login,
                                                            self.vm_pswd)
        # check network settings
        serv_t2n1_available = self.check_l2_connectivity(self.server1_t1n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           HWaddr_server_t2n1)
        self.assertEqual(-1, serv_t2n1_available)
        serv_t1n1_available = self.check_l2_connectivity(self.server1_t2n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           HWaddr_server_t1n1)
        self.assertEqual(-1, serv_t1n1_available)

    @attr(type='negative')
    def test_l2_connectivity_diff_nets(self):
        """Negative: Servers from different networks within the same tenant
           should not have L2 connectivity"""
        HWaddr_server_t1n1 = self.get_MAC_addr_of_server(self.server1_t1n1_ip,
                                                            self.vm_login,
                                                            self.vm_pswd)
        HWaddr_server_t1n2 = self.get_MAC_addr_of_server(self.server1_t1n2_ip,
                                                            self.vm_login,
                                                            self.vm_pswd)
        # check network settings
        serv_t1n2_available = self.check_l2_connectivity(self.server1_t1n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           HWaddr_server_t1n2)
        self.assertEqual(-1, serv_t1n2_available)
        serv_t1n1_available = self.check_l2_connectivity(self.server1_t1n2_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           HWaddr_server_t1n1)
        self.assertEqual(-1, serv_t1n1_available)

    @attr(type='positive')
    def test_l2_connectivity_same_net(self):
        """Servers from the same network should have L2 connectivity"""
        HWaddr_server1_t1n1 = self.get_MAC_addr_of_server(self.server1_t1n1_ip,
                                                            self.vm_login,
                                                            self.vm_pswd)
        HWaddr_server2_t1n1 = self.get_MAC_addr_of_server(self.server2_t1n1_ip,
                                                            self.vm_login,
                                                            self.vm_pswd)
        # check network settings
        serv2_t1n1_available = self.check_l2_connectivity(self.server1_t1n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           HWaddr_server2_t1n1)
        self.assertNotEqual(-1, serv2_t1n1_available)
        serv1_t1n1_available = self.check_l2_connectivity(self.server2_t1n1_ip,
                                           self.vm_login,
                                           self.vm_pswd,
                                           HWaddr_server1_t1n1)
        self.assertNotEqual(-1, serv1_t1n1_available)

    @attr(type='positive')
    def test_delete_unused_net(self):
        """Delete network that is not used"""
        name = rand_name('tempest-network')
        resp, body = self.client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        resp, body = self.client.delete_network(network['id'])
        self.assertEqual('204', resp['status'])

    @attr(type='negative')
    def test_delete_net_in_use(self):
        """Deletion of network that is used should be prohibited"""
        res = self.client.delete_network(self.net1_id)
        self.assertEqual('409', res.resp['status'])
        openstack_configuration = self.show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        # Read the output and check that network for VM was net deleted
        vlan_present = False
        for line in iter(openstack_configuration.stdout.readline, ''):
            #if net id and hostname are found in the same string
            if str(line).find(self.net1_id) != -1:
                vlan_present = True
                break
        self.assertTrue(vlan_present)

    @attr(type='positive')
    def test_reboot_vEOS(self):
        """All network settings should remain after vEOS reboot"""
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        openstack_configuration = self.show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        # Read the output
        bufferdata1 = openstack_configuration.stdout.read()
        #Reboot vEOS
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip, username=self.vEOS_login, password=self.vEOS_pswd)
        ssh.exec_command("init 6")
        ssh.close()
        #check network settings after reboot
        resp, body2 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        self.assertEqual(body1, body2)
        openstack_configuration = self.show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        # Read the output
        bufferdata2 = openstack_configuration.stdout.read()
        self.assertEqual(bufferdata1, bufferdata2)

    @attr(type='positive')
    def test_reboot_Quantum(self):
        """All network settings should remain after Quantum reboot"""
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        openstack_configuration = self.show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        bufferdata1 = openstack_configuration.stdout.read()
        #Reboot Quantum
        Popen("service quantum-server restart", shell=True)
        res = Popen("service quantum-server status", shell=True)
        while str(res).find("start/running") == -1:
            res = Popen("service quantum-server status", shell=True)
        #check network settings after reboot
        resp, body2 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        self.assertEqual(body1, body2)
        openstack_configuration = self.show_configuration_in_vEOS(self.vEOS_ip,
                                        self.vEOS_login,
                                        self.vEOS_pswd)
        bufferdata2 = openstack_configuration.stdout.read()
        self.assertEqual(bufferdata1, bufferdata2)

    @attr(type='negative')
    def test_create_network_vEOS_down(self):
        """Negative: can not create network when vEOS is down"""
        # Shut down vEOS - disconnect
        Popen("ifconfig %s %s down" % (self.vEOS_if, self.vEOS_ip), shell=True)
        #try to create network
        name = rand_name('tempest-network')
        res = self.client.create_network(name)
        self.assertEqual('400', res.resp['status'])

    @attr(type='negative')
    def test_delete_unused_net_vEOS_down(self):
        """Negative: can not delete unused network when vEOS id down"""
        name = rand_name('tempest-network')
        resp, body = self.client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        # Shut down vEOS - disconnect
        Popen("ifconfig %s %s down" % (self.vEOS_if, self.vEOS_ip), shell=True)
        #try to delete network
        resp, body = self.client.delete_network(network['id'])
        self.assertEqual('404', resp['status'])

    @attr(type='negative')
    def test_create_server_vEOS_down(self):
        """Negative: can not create server when vEOS is down"""
        # Shut down vEOS - disconnect
        Popen("ifconfig %s %s down" % (self.vEOS_if, self.vEOS_ip), shell=True)
        #
        #try to create server
        name = rand_name('tempest-server')
        res = self.servers_client.create_server(name,
                                                 self.image_ref,
                                                 self.flavor_ref.
                                                 self.net_id1)
        self.assertEqual('404', res.resp['status'])

    @classmethod
    def create_test_server(cls, server_name, image_ref, flavor_ref, net_id):
        """Utility that returns a test server"""
        resp, body = cls.servers_client.create_server(server_name,
                                                       image_ref,
                                                       flavor_ref,
                                                       net_id)
        server_id = body['id']
        cls.assertEqual('202', resp['status'])
        cls.servers_client.wait_for_server_status(body['id'], 'ACTIVE')
        resp, body = cls.servers_client.get_server(body['id'],)
        cls.assertEqual('200', resp['status'])
        network_attached = body['addresses'].popitem()
        server_ip = network_attached.get('addr')
        return server_id, server_ip

    @classmethod
    def show_configuration_in_vEOS(cls, ip, username, password):
        """Utility that returns openstack configuration from vEOS"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username, password)
        # show network settings
        ssh.exec_command("en")
        ssh.exec_command("config")
        ssh.exec_command("management openstack")
        proc = ssh.exec_command("show openstack")
        ssh.close()
        return proc

    @classmethod
    def get_MAC_addr_of_server(cls, ip, username, password):
        """Utility that returns MAC-address for server"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username, password)
        #Get MAC address
        output = ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output
        data = output.stdout.read()
        HWaddr = str(data)[str(data).find("HWaddr"):len(str(data))]
        HWaddr = str(HWaddr).strip()
        ssh.close()
        return HWaddr
    @classmethod
    def check_l2_connectivity(cls, ip, username, password, HWaddr):
        """Utility that returns the state of l2connectivity"""
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(ip, username, password)
        # check network settings
        output = ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = output.stdout.read()
        found = str(bufferdata).find(HWaddr)
        ssh.close()
        return found

