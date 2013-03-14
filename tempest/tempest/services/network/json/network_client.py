import json
from tempest.common.rest_client import RestClient


class NetworkClient(RestClient):

    def __init__(self, config, username, password, auth_url, tenant_name=None):
        super(NetworkClient, self).__init__(config, username, password,
                                            auth_url, tenant_name)
        self.service = self.config.network.catalog_type

    def list_networks(self):
        resp, body = self.get('networks')
        body = json.loads(body)
        return resp, body

    def create_network(self, name, key="network"):
        post_body = {
            key: {
                'name': name,
            }
        }
        headers = {'Content-Type': 'application/json'}
        body = json.dumps(post_body)
        resp, body = self.post('networks', headers=headers, body=body)
        body = json.loads(body)
        return resp, body

    def list_networks_details(self):
        resp, body = self.get('networks/detail')
        body = json.loads(body)
        return resp, body

    def get_network(self, uuid):
        resp, body = self.get('networks/%s' % uuid)
        body = json.loads(body)
        return resp, body

    def get_network_details(self, uuid):
        resp, body = self.get('networks/%s/detail' % uuid)
        body = json.loads(body)
        return resp, body

    def delete_network(self, uuid):
        resp, body = self.delete('networks/%s' % uuid)
        return resp, body
    
    def create_subnet(self, network_id, cidr, name, key="subnet"):
        post_body = {
            key: {
                  'network_id': network_id,
                  'cidr': cidr,
                  'name': name
            }
        }
        headers = {'Content-Type': 'application/json'}
        body = json.dumps(post_body)
        resp, body = self.post('subnets', headers=headers, body=body)
        body = json.loads(body)
        return resp, body

    def delete_subnet(self, uuid):
        resp, body = self.delete('subnets/%s' % uuid)
        return resp, body

    def create_port(self, name, network_id, state=None, key='port'):
        if not state:
            state = 'ACTIVE'
        post_body = {
            key: {
                'name': name,
                'admin_state_up': True,
                'network_id': network_id,
            }
        }
        headers = {'Content-Type': 'application/json'}
        body = json.dumps(post_body)
        resp, body = self.post('ports.json', headers=headers, body=body)
        body = json.loads(body)
        return resp, body

    def delete_port(self, port_id):
        resp, body = self.delete('ports/%s.json' % port_id)
        return resp, body

    def list_ports(self):
        #resp, body = self.get('networks/%s/ports.json' % network_id)
        resp, body = self.get('/ports.json')
        body = json.loads(body)
        return resp, body

    def list_port_details(self, network_id):
        url = '/ports/detail.json' % network_id
        resp, body = self.get(url)
        body = json.loads(body)
        return resp, body

    def attach_port(self, network_id, port_id, interface_id):
        post_body = {
            'attachment': {
                'id': interface_id
            }
        }
        headers = {'Content-Type': 'application/json'}
        body = json.dumps(post_body)
        url = 'networks/%s/ports/%s/attachment.json' % (network_id, port_id)
        resp, body = self.put(url, headers=headers, body=body)
        return resp, body

    def detach_port(self, network_id, port_id):
        url = 'networks/%s/ports/%s/attachment.json' % (network_id, port_id)
        resp, body = self.delete(url)
        return resp, body

    def list_port_attachment(self, network_id, port_id):
        url = 'networks/%s/ports/%s/attachment.json' % (network_id, port_id)
        resp, body = self.get(url)
        body = json.loads(body)
        return resp, body
