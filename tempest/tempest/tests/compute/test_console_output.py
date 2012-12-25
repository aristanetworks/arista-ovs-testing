# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack, LLC
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

from nose.plugins.attrib import attr
import unittest2 as unittest

from tempest import exceptions
from tempest.common.utils.data_utils import rand_name
from tempest.tests.compute.base import BaseComputeTest


class ConsoleOutputTest(BaseComputeTest):

    @classmethod
    def setUpClass(cls):
        super(ConsoleOutputTest, cls).setUpClass()
        cls.client = cls.console_outputs_client
        cls.servers_client = cls.servers_client
        cls.name = rand_name('server')
        resp, server = cls.servers_client.create_server(cls.name,
                                                        cls.image_ref,
                                                        cls.flavor_ref)
        cls.server_id = server['id']

        cls.servers_client.wait_for_server_status(cls.server_id, 'ACTIVE')

    @classmethod
    def tearDownClass(cls):
        cls.servers_client.delete_server(cls.server_id)
        super(ConsoleOutputTest, cls).tearDownClass()

    @attr(type='positive')
    def test_get_console_output(self):
        """
        Positive test:Should be able to GET the console output
        for a given server_id and number of lines
        """
        def get_output():
            resp, output = self.client.get_console_output(self.server_id, 10)
            self.assertEqual(200, resp.status)
            self.assertNotEqual(output, None)
            lines = len(output.split('\n'))
            self.assertEqual(lines, 10)
        self.wait_for(get_output)

    @attr(type='negative')
    def test_get_console_output_invalid_server_id(self):
        """
        Negative test: Should not be able to get the console output
        for an invalid server_id
        """
        try:
            resp, output = self.client.get_console_output('!@#$%^&*()', 10)
        except exceptions.NotFound:
            pass

    @attr(type='positive')
    @unittest.skip('Until tempest bug 1014683 is fixed.')
    def test_get_console_output_server_id_in_reboot_status(self):
        """
        Positive test:Should be able to GET the console output
        for a given server_id in reboot status
        """
        try:
            resp, output = self.servers_client.reboot(self.server_id, 'SOFT')
            self.servers_client.wait_for_server_status(self.server_id,
                                                       'REBOOT')
            resp, server = self.servers_client.get_server(self.server_id)
            if (server['status'] == 'REBOOT'):
                resp, output = self.client.get_console_output(self.server_id,
                                                              10)
                self.assertEqual(200, resp.status)
                self.assertNotEqual(output, None)
                lines = len(output.split('\n'))
                self.assertEqual(lines, 10)
            else:
                self.fail("Could not capture instance in Reboot status")
        finally:
            self.servers_client.wait_for_server_status(self.server_id,
                                                       'ACTIVE')
