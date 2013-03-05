Auto tests for Arista OVS plugin extension
==========================================

Repository contains code for Arista OVS (Open vSwitch) Quantum plugin extension.

To run all tests for Arista OVS plugin:

1. git clone https://github.com/Mirantis/arista-ovs-testing.git
2. cd arista-ovs-testing/tempest
2. set up tempest.conf file (modify arista-ovs-testing/tempest/etc/tempest.conf.sample and save as tempest.conf)
        Parameters to be set:

        [identity]
        host = Controller node IP

        [compute]
        use_host_name = set True if use 'host' (was suitable for Arista lab)
        username = set to admin
        password = admin's password
        tenant_name = admin's tenant (admin)
        alt_username = set to demo (or other user from another tenant)
        alt_password = demo's password
        alt_tenant_name = demo's tenant
        image_ref = image id to be used for VM  boot
        image_ref_alt = alternative image id (can be  the same if only one is provided)
        flavor_ref = flavor id to be used for VM boot
        flavor_ref_alt = alternative flavor id
        ssh_user = user to ssh into VM
        ssh_pswd = password to ssh into  VM

        [image]
        host = usually Controller node IP (read tempest.conf for more details)
        port = port number for Image API
        username = user without administrative privileges (demo)
        password = demo's password
        tenant_name = demo's tenant name

        [compute-admin]
        username = admin
        password = admin's password
        tenant_name = admin's tenant name

        [network]
        api_version = set according to environment, e.g. /v2.0 (use slash)
        tenant1_net1_id = set to id of network, that has subnet and belongs to admin tenant (needed for  L2 connectivity check)
        namespace1_1 = corresponding namespace
        tenant2_net1_id = set to id of the second network, that has subnet and belongs to admin tenant (needed for  L2 connectivity check)
        namespace1_2 = corresponding namespace
        tenant2_net1_id = set to id of network, that has subnet and belongs to non-admin tenant and user (needed for  L2 connectivity check)
        namespace2_1 = corresponding namespace
        arista_driver_ini = path to arista_driver.ini file
        dhcp_agent_ini = path to dhcp_agent.ini file
        vEOS_is_apart = set True if vEOS and TOR separated (as was for Arista lab)

        [identity-admin]
        username = admin
        password = admin's password
        tenant_name = admin's tenant name

3. To run the full test suite:
        s-admin@os-clrl:/opt/stack/arista-ovs-testing/tempest$ nosetests -s -v tempest/tests/network/test_arista_ovs_plugin.py

        Output (expected):

        nose.config: INFO: Ignoring files matching ['^\\.', '^_', '^setup\\.py$']
        001 - Creates a network for a given tenant ... ok
        002 - Create instance providing net id ... ok
        003 - Create instance without providing net id ... ok
        004 - All network settings should remain after instance reboot ... ok
        005 - Negative: Servers from different tenants ... ok                                                                                                                                                                                               006 - Negative: Servers from different networks within the same ... ok
        007 - Servers from the same network should have L2 connectivity ... ok
        008 - Delete network that is not used ... ok
        009 - Negative: Deletion of network that is used should be prohibited ... ok
        010 - All network settings should remain after Quantum reboot ... ok
        011 - Unused VLAN remains after the Server deletion ... ok
        012 - VLAN in use remains after the Server deletion ... ok
        013 - No new tenant-networks in vEOS after sync ... ok                                                                                                                                                                                              014 - Unused network will be deleted  after vEOS sync ... ok
        015 - Create server when vEOS is down and required VLAN exists ... ok
        016 - Negative: can not create server when vEOS is down ... ok
        017 - vEOS should set up VLANs according to Quantum DB ... ok
        018 - Creates a server with network via port instantiation ... ok

        ----------------------------------------------------------------------
        Ran 18 tests in 2462.041s
        OK

   To run single test:
        os-admin@os-clrl:/opt/stack/arista-ovs-testing/tempest$ nosetests -s -v tempest/tests/network/test_arista_ovs_plugin.py:L2Test.test_001_create_network

        Otput (expected):

        nose.config: INFO: Ignoring files matching ['^\\.', '^_', '^setup\\.py$']
        001 - Creates a network for a given tenant ... ok

        ----------------------------------------------------------------------
        Ran 1 test in 16.619s
        OK

4. For more details about tempest.conf setup, please, refer to tempest.conf.sample
