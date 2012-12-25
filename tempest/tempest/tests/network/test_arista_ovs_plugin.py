
from nose.plugins.attrib import attr
from tempest import openstack
from tempest.common.utils.data_utils import rand_name
from tempest.tests.network import base


from paramiko import SSHClient
from paramiko import AutoAddPolicy

from subprocess import Popen, PIPE

class L2Test(base.BaseNetworkTest):

    @classmethod
    def setUpClass(cls):
        super(L2Test, cls).setUpClass()
        cls.os = openstack.Manager()
        
        #set up Network client
        cls.network_client = cls.os.network_client
        cls.config = cls.os.config
        
        cls.vEOS_ip = '172.0.0.0'
        cls.vEOS_login = 'admin'
        cls.vEOS_pswd = 'r00tme'
        
        cls.tor_ip = '1.1.1.1'
        cls.tor_login = 'admin'
        cls.tor_pswd = 'r00tme'
        
        #set up Admin Client
        cls.admin_client = cls.os.admin_client
        
        
        #set up Server Client          
        cls.servers_client = cls.servers_client
        cls.image_ref = cls.config.compute.image_ref        
        cls.flavor_ref = cls.config.compute.flavor_ref     
        cls.vm_login = cls.config.compute.ssh_user
        cls.vm_pswd = cls.config.compute.ssh_password
        
        #test networks     
        #tenant 1   
        cls.net_id1 = cls.config.network.net1_id
        resp, body = cls.network_client.get_network(cls.net_id1)
        cls.net1_name = body['name']
        
        
        cls.net_id3 =cls.config.network.net2_id
        
        #tenant 2
        cls.net_id2 =cls.config.network.net2_id

        
        # create test servers
        # two servers within one network same tenant
        # VM1
        cls.name1 = rand_name('tempest-setup-server')
        resp, body = cls.servers_client.create_server(cls.name1,
                                                 cls.image_ref,
                                                 cls.flavor_ref,
                                                 networks = cls.net_id1)
        cls.server1_id = body['id']
        cls.servers_client.wait_for_server_status(cls.server1_id, 'ACTIVE')
        resp, body = cls.get_server(cls.server1_id)
        network_attached = body['addresses'].popitem()
        cls.vm1_ip = network_attached.get('addr')
        # VM2
        name2 = rand_name('tempest-setup-server')
        resp, body = cls.servers_client.create_server(name2,
                                                 cls.image_ref,
                                                 cls.flavor_ref,
                                                 networks = cls.net_id1)
        cls.server2_id = body['id']
        cls.servers_client.wait_for_server_status(cls.server2_id, 'ACTIVE')
        resp, body = cls.get_server(cls.server2_id)
        network_attached = body['addresses'].popitem()
        cls.vm2_ip = network_attached.get('addr')
        
        # VM3 - same tenant, another network
        name3 = rand_name('tempest-setup-server')
        resp, body = cls.servers_client.create_server(name3,
                                                 cls.image_ref,
                                                 cls.flavor_ref,
                                                 networks = cls.net_id3)
        cls.server3_id = body['id']
        cls.servers_client.wait_for_server_status(cls.server3_id, 'ACTIVE')
        resp, body = cls.get_server(cls.server3_id)
        network_attached = body['addresses'].popitem()
        cls.vm3_ip = network_attached.get('addr')
        
        
        # create test server from another tenant (network) - VM4
        name4 = rand_name('tempest-setup-server')
        resp, body = cls.servers_client.create_server(name4,
                                                 cls.image_ref,
                                                 cls.flavor_ref,
                                                 networks = cls.net_id2)
        cls.server4_id = body['id']
        cls.servers_client.wait_for_server_status(cls.server4_id, 'ACTIVE')
        resp, body = cls.get_server(cls.server4_id)
        network_attached = body['addresses'].popitem()
        cls.vm4_ip = network_attached.get('addr')
        


        
    @attr(type='positive')
    def test_create_network(self):
        """Creates a network for a tenant"""
        #create net and check in Quantum
        name = rand_name('tempest-network')
        resp, body = self.network_client.create_network(name)
        self.assertEqual('201', resp['status'])
       
     
    @attr(type = 'positive')    
    def test_create_server_with_network(self):
        """Create instance providing net id"""
        #use network from Set Up
        #create server with net
        name = rand_name('tempest-server')
        resp, body = self.servers_client.create_server(name,
                                                 self.image_ref,
                                                 self.flavor_ref,
                                                 networks = self.net_id)
        server_id = body['id']
        self.client.wait_for_server_status(server_id, 'ACTIVE')
        #get hostname of Compute host
        resp, server = self.server_client.get_server(server_id)
        host_name = server['host']
        #ssh into vEOS   
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
        # check network settings
        ssh.exec_command("en")
        ssh.exec_command("config")
        ssh.exec_command("management openstack")
        proc = ssh.exec_command("show openstack")
        # Read the output and check that VLAN for VM was created
        vlan_created = False
        for line in iter(proc.stdout.readline, ''):
            if str(line).find(self.net_id)!=1 and str(line).find(host_name)!=1:
                vlan_created = True
                break
        self.assertTrue(vlan_created)
        ssh.close()
        
        
    @attr(type = 'positive')
    def test_create_server_without_network(self):
        """Create instance without providing net id"""
        #create server without net
        name = rand_name('tempest-server')
        resp, body = self.servers_client.create_server(name,
                                                 self.image_ref,
                                                 self.flavor_ref)
        self.client.wait_for_server_status(body['id'], 'ACTIVE')           
        #get hostname of Compute host
        resp, server = self.server_client.get_server(body['id'])
        host_name = server['host']
        # get list of networks attached     
        networks_attached_names = server['addresses'].keys()  
        net_ids  = []
        #
        #    Fill net_ids with corresponding values for networks_attached_names
        #
        # if some networks are attached to VM   
        if len(net_ids)!=0:   
            #ssh into vEOS   
            ssh=SSHClient()
            ssh.set_missing_host_key_policy(AutoAddPolicy())
            ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
            # check network settings
            ssh.exec_command("en")
            ssh.exec_command("config")
            ssh.exec_command("management openstack")
            proc = ssh.exec_command("show openstack")
            number_vlan_created = 0 
            for line in iter(proc.stdout.readline, ''):
                for i in range(len(net_ids)):
                    if str(line).find(net_ids[i]) != 1 and str(line).find(host_name) != 1:
                        number_vlan_created = number_vlan_created+1
            self.assertEqual(len(net_ids),number_vlan_created)
        ssh.close()
                        
        
        
    @attr(type = 'positive')
    def test_reboot_server(self):
        """All network settings should remain after the instance reboot"""
        # get list of networks attached
        resp, server = self.servers_client.get_server(self.server1_id)
        networks_attached1 = server['addresses'].keys()  
        #reboot server
        resp, body = self.client.reboot(self.server1_id, 'HARD')
        self.assertEqual(202, resp.status)
        self.client.wait_for_server_status(self.server1_id, 'ACTIVE')
        # get list of networks attached
        resp, server = self.servers_client.get_server(self.server1_id)
        networks_attached2 = server['addresses'].keys()  
        self.assertEqual(networks_attached1,networks_attached2)        
        #get hostname of Compute host        
        host_name = server['host']         
        net_ids  = []
        #
        #    Fill net_ids with corresponding values for networks_attached2
        #
        # if some networks are attached to VM   
        if len(net_ids)!=0:   
            #ssh into vEOS   
            ssh=SSHClient()
            ssh.set_missing_host_key_policy(AutoAddPolicy())
            ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
            # check network settings
            ssh.exec_command("en")
            ssh.exec_command("config")
            ssh.exec_command("management openstack")
            proc = ssh.exec_command("show openstack")
            number_vlan_created = 0 
            for line in iter(proc.stdout.readline, ''):
                for i in range(len(net_ids)):
                    if str(line).find(net_ids[i]) != 1 and str(line).find(host_name) != 1:
                        number_vlan_created = number_vlan_created+1
            self.assertEqual(len(net_ids),number_vlan_created)
        ssh.close()
        
         
        
    @attr(type = 'negative')
    def test_l2_connectivity_diff_tenants(self):
        """Negative: Servers from different tenants should not have L2 connectivity"""
        #ssh into VM1       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm1_ip,username=self.vm_login,password=self.vm_pswd)
        #Get MAC address
        stdin, stdout, stderr=ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output
        HWaddr = stdout.read() 
        HWaddr1 = str(HWaddr)[str(HWaddr).find("HWaddr"):len(str(HWaddr))]
        HWaddr1 = str(HWaddr1).strip()
        ssh.close()
        
        #ssh into VM4       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm4_ip,username=self.vm_login,password=self.vm_pswd)
        #Get MAC address
        stdin, stdout, stderr=ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output [{"version": 4, "addr": "192.168.2.6"}]
        HWaddr = stdout.read() 
        HWaddr2 = str(HWaddr)[str(HWaddr).find("HWaddr"):len(str(HWaddr))]
        HWaddr2 = str(HWaddr2).strip()        
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = stdout.read() 
        self.assertEqual(-1,str(bufferdata).find(HWaddr1), "Server from another network was found")
        ssh.close()
        
        #ssh into VM1 again       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm1_ip,username=self.vm_login,password=self.vm_pswd)             
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = stdout.read() 
        self.assertEqual(-1,str(bufferdata).find(HWaddr2), "Server from another network was found")
        ssh.close()
            
        
    @attr(type = 'negative')
    def test_l2_connectivity_diff_nets(self):
        """Negative: Servers from different networks within the same tenant should not have L2 connectivity"""     
        #ssh into VM1       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm1_ip,username=self.vm_login,password=self.vm_pswd)
        #Get MAC address
        stdin, stdout, stderr=ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output
        HWaddr = stdout.read() 
        HWaddr1 = str(HWaddr)[str(HWaddr).find("HWaddr"):len(str(HWaddr))]
        HWaddr1 = str(HWaddr1).strip()
        ssh.close()
        
        #ssh into VM4       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm3_ip,username=self.vm_login,password=self.vm_pswd)
        #Get MAC address
        stdin, stdout, stderr=ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output [{"version": 4, "addr": "192.168.2.6"}]
        HWaddr = stdout.read() 
        HWaddr2 = str(HWaddr)[str(HWaddr).find("HWaddr"):len(str(HWaddr))]
        HWaddr2 = str(HWaddr2).strip()        
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = stdout.read() 
        self.assertEqual(-1,str(bufferdata).find(HWaddr1), "Server from another network was found")
        ssh.close()
        
        #ssh into VM1 again       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm1_ip,username=self.vm_login,password=self.vm_pswd)             
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = stdout.read() 
        self.assertEqual(-1,str(bufferdata).find(HWaddr2), "Server from another network was found")
        ssh.close()   
        
        
    @attr(type = 'positive')
    def test_l2_connectivity_same_net(self):
        """Servers from the same network should have L2 connectivity"""        
                #ssh into VM1       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm1_ip,username=self.vm_login,password=self.vm_pswd)
        #Get MAC address
        stdin, stdout, stderr=ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output
        HWaddr = stdout.read() 
        HWaddr1 = str(HWaddr)[str(HWaddr).find("HWaddr"):len(str(HWaddr))]
        HWaddr1 = str(HWaddr1).strip()
        ssh.close()
        
        #ssh into VM4       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm2_ip,username=self.vm_login,password=self.vm_pswd)
        #Get MAC address
        stdin, stdout, stderr=ssh.exec_command("ifconfig -a | grep -m 1 HWaddr")
        # Read the output [{"version": 4, "addr": "192.168.2.6"}]
        HWaddr = stdout.read() 
        HWaddr2 = str(HWaddr)[str(HWaddr).find("HWaddr"):len(str(HWaddr))]
        HWaddr2 = str(HWaddr2).strip()        
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = stdout.read() 
        self.assertEqual(-1,str(bufferdata).find(HWaddr1), "Server from another network was found")
        ssh.close()
        
        #ssh into VM1 again       
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vm1_ip,username=self.vm_login,password=self.vm_pswd)             
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("arp-scan -l")
        # Read the output
        bufferdata = stdout.read() 
        self.assertEqual(-1,str(bufferdata).find(HWaddr2), "Server from another network was found")
        ssh.close()  
        
    @attr(type = 'positive')
    def test_delete_unused_net(self):               
        """Delete network that is not used"""
        name = rand_name('tempest-network')
        resp, body = self.client.create_network(name)
        self.assertEqual('201', resp['status'])
        network = body['network']
        self.assertTrue(network['id'] is not None)
        resp, body = self.client.delete_network(network['id'])
        self.assertEqual('204', resp['status'])
        
    @attr(type = 'negative')
    def test_delete_net_in_use(self):               
        """Deletion of network that is used should be prohibited"""
        resp, body = self.client.delete_network(self.net1_id)
        self.assertEqual('409', resp['status'])
        #ssh into vEOS  
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
        # check network settings
        ssh.exec_command("en")
        ssh.exec_command("config")
        ssh.exec_command("management openstack")
        proc = ssh.exec_command("show openstack")
        # Read the output and check that VLAN for VM was created
        #
        # TBD
        #
        ssh.close()
        
    @attr(type = 'positive')
    def test_reboot_vEOS(self):   
        """All network settings should remain after vEOS reboot"""
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        #ssh into vEOS  
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("show openstack")
        # Read the output
        bufferdata1 = stdout.read() 
        # Ssh into TORs 
        #
        # TBD
        #
        #Reboot vEOS
        stdin, stdout, stderr=ssh.exec_command("init 6")
        ssh.close()
        #check network settings after reboot
        resp,body2 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        self.assertEqual(body1, body2)
        #ssh into vEOS  
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
        # check network settings in vEOS
        stdin, stdout, stderr=ssh.exec_command("show openstack")
        # Read the output
        bufferdata2 = stdout.read() 
        self.assertEqual(bufferdata1, bufferdata2)
        ssh.close()
        # Ssh into TORs 
        #
        # TBD
        #
        #Reboot vEOS
        
        
        
    @attr(type = 'positive')
    def test_reboot_Quantum(self):   
        """All network settings should remain after Quantum reboot"""
        resp, body1 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        #ssh into vEOS  
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
        # check network settings
        stdin, stdout, stderr=ssh.exec_command("show openstack")
        # Read the output
        bufferdata1 = stdout.read() 
        # Ssh into TORs 
        #
        # TBD
        #       
        ssh.close()
        
        #Reboot vEOS 
        Popen("service quantum-server restart", shell=True)
        res = Popen("service quantum-server status", shell=True)
        while str(res).find("start/running")==-1:
            res = Popen("service quantum-server status", shell=True)
        #check network settings after reboot
        resp,body2 = self.network_client.list_networks()
        self.assertEqual('200', resp['status'])
        self.assertEqual(body1, body2)
        #ssh into vEOS  
        ssh=SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(self.vEOS_ip,username=self.vEOS_login,password=self.vEOS_pswd)
        # check network settings in vEOS
        stdin, stdout, stderr=ssh.exec_command("show openstack")
        # Read the output
        bufferdata2 = stdout.read() 
        self.assertEqual(bufferdata1, bufferdata2)
        ssh.close()
        # Ssh into TORs 
        #
        # TBD
        #
        #Reboot vEOS
               
    @attr(type = 'positive')
    def test_create_network_vEOS_down(self):   
        """Negative: can not create network when vEOS is down""" 
        # Shut down vEOS 
        #
        # TBD
        # res = Popen("ifconfig eth0 10.0.0.1 down", shell=True)
        #
        #try to create network
        name = rand_name('tempest-network')
        resp, body = self.client.create_network(name)
        self.assertEqual('400', resp['status'])
        
    @attr(type = 'negative')
    def test_create_server_vEOS_down(self):  
        """Negative: can not delete create server when vEOS is down"""                
        # Shut down vEOS 
        #
        # TBD 
        # res = Popen("ifconfig eth0 10.0.0.1 down", shell=True)
        #
        #try to create network                
        resp, body = self.client.delete_network(self.net1_id)
        self.assertEqual('404', resp['status'])
        
    @attr(type = 'positive')
    def test_delete_server(self):  
        """Server deletion should invoke VLAN deletion on vEOS if VLAN is not used by other VMs""" 
        #
        # TBD
        #   
        
    @attr(type = 'negative')
    def test_delete_server_vEOS_down(self): 
        """Negative: can not delete server when vEOS is down"""    
        #
        # TBD
        #

        
        
        
        
        
        
        
        
        
        
        

