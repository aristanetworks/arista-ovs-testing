Auto tests for Arista OVS plugin extension
==========================================

Repository contains code for Arista OVS (Open vSwitch) Quantum plugin extension.

To run all tests for Arista OVS plugin:

1. cd arista-ovs-testing/tempest
2. set up tempest.conf file (arista-ovs-testing/tempest/etc/tempest.conf)
3. nosetests -s -v tempest/tests/network/test_arista_ovs_plugin.py



