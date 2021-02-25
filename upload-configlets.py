#!/usr/bin/env python3

__author__ = 'Petr Ankudinov'

# *** TESTED FOR CVP VERSIONS:
# ***  2018.2.2

import json
import requests
import sys
from time import time as time
from datetime import datetime as datetime
import os
import yaml

# disable cvprac insecure warnings
# can be removed if valid certificate is installed on CVP
import requests.packages.urllib3 as urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CVP(object):

    def __init__(self, url_prefix, cvp_username, cvp_password):
        self.session = requests.session()
        self.session.verify = False
        self.cvp_url_prefix = url_prefix
        self.timeout = 180
        self.temp_task_list = list()  # list of temp tasks to save and execute
        # authenticate
        url = self.cvp_url_prefix + '/web/login/authenticate.do'
        authdata = {'userId': cvp_username, 'password': cvp_password}
        resp = self.session.post(url, data=json.dumps(
            authdata), timeout=self.timeout)
        if resp.raise_for_status():
            sys.exit('ERROR: Received wrong status code when connecting to CVP!')

    @staticmethod
    def handle_errors(r, task_description='A request to CVP REST API'):
        # handles possible CVP or requests errors
        if 'errorCode' in r.json():
            sys.exit('%s failed!\nERROR code: %s\n   message: %s' % (
                task_description, r.json()['errorCode'], r.json()[
                    'errorMessage']
            ))
        if r.raise_for_status():
            err_msg = 'ERROR: %s failed! Wrong status code %s received' % (
                task_description, r.status_code)
            sys.exit(err_msg)

    def get_configlets(self):
        url = self.cvp_url_prefix + \
            '/cvpservice/configlet/getConfiglets.do?startIndex=0&endIndex=0'
        resp = self.session.get(url, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Collecting configlet inventory')
        d = dict()
        for configlet in resp.json()['data']:
            d.update({
                configlet['key']: configlet
            })
        return d

    def get_devices(self, provisioned=False):
        # provisioned: True - provisioned only, False - full inventory, including Undefined container
        url = self.cvp_url_prefix + '/cvpservice/inventory/devices?provisioned=%s' % provisioned
        resp = self.session.get(url, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Collecting device inventory')
        d = dict()
        for device in resp.json():
            d.update({
                device['serialNumber']: device
            })
        return d

    def get_containers(self):
        url = self.cvp_url_prefix + '/cvpservice/inventory/containers'
        resp = self.session.get(url, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Collecting container inventory')
        d = dict()
        for container in resp.json():
            d.update({
                container['Key']: container
            })
        return d

    def load_j2_tempate(self, template_name):
        configlet_inventory = self.get_configlets()
        for cfglet_id, cfglet_details in configlet_inventory.items():
            if cfglet_details['name'] == template_name:
                return cfglet_details['config']

    def find_container_id(self, container_name):
        container_inventory = self.get_containers()
        for container_key, container_details in container_inventory.items():
            if container_details['Name'] == container_name:
                return container_key

    def find_builder_id(self, builder_name):
        configlet_inventory = self.get_configlets()
        for cfglet_id, cfglet_details in configlet_inventory.items():
            if (cfglet_details['name'] == builder_name) and (cfglet_details['type'] == 'Builder'):
                return cfglet_id

    def get_device_serials_in_container(self, container_key):
        url = self.cvp_url_prefix + \
            '/cvpservice/provisioning/getNetElementList.do?nodeId=%s&startIndex=0&endIndex=0&ignoreAdd=true' % container_key
        resp = self.session.get(url, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Collecting devices in a container')
        d = dict()
        for device in resp.json()['netElementList']:
            d.update({
                device['serialNumber']: device
            })
        return d

    def generate_configlets_from_builder(self, builder_key, netelement_key_list, container_key):
        url = self.cvp_url_prefix + '/cvpservice/configlet/autoConfigletGenerator.do'
        payload = {
            'configletBuilderId': builder_key,
            'netElementIds': netelement_key_list,
            'containerId': container_key,
            'pageType': 'string'
        }
        resp = self.session.post(
            url, data=json.dumps(payload), timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Generating updated configlets from builder')
        return resp.json()

    def get_configlets_for_a_device(self, netelement_id):
        url = self.cvp_url_prefix + \
            '/cvpservice/provisioning/getConfigletsByNetElementId.do?netElementId=%s&startIndex=0&endIndex=0' % netelement_id
        resp = self.session.get(url, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Collecting container inventory')
        assigned_configlet_list = resp.json()['configletList']
        return assigned_configlet_list

    def addTempTask(self, temp_task_data, info=''):
        # used to format and add new task to the temp task list
        taskId = len(self.temp_task_list) + 1
        d = {
            "taskId": taskId,
            "info": info,
            "infoPreview": info,
        }
        d.update(temp_task_data)
        self.temp_task_list.append(d)

        return d

    def reassign_configlets_to_device(self, device, configlet_list_to_unassign, configlet_list_to_assign):

        info = "Reassigning configlets to device %s" % device['serialNumber']

        c_names_to_remove = list()
        c_keys_to_remove = list()
        b_names_to_remove = list()
        b_keys_to_remove = list()
        c_names_to_add = list()
        c_keys_to_add = list()
        b_names_to_add = list()
        b_keys_to_add = list()

        for cfglet in configlet_list_to_unassign:
            if cfglet['type'] == 'Builder':
                b_names_to_remove.append(cfglet['name'])
                b_keys_to_remove.append(cfglet['key'])
            else:
                c_names_to_remove.append(cfglet['name'])
                c_keys_to_remove.append(cfglet['key'])

        for cfglet in configlet_list_to_assign:
            if cfglet['type'] == 'Builder':
                b_names_to_add.append(cfglet['name'])
                b_keys_to_add.append(cfglet['key'])
            else:
                c_names_to_add.append(cfglet['name'])
                c_keys_to_add.append(cfglet['key'])

        task_d = {
            'action': 'associate',
            'nodeType': 'configlet',
            'nodeId': '',
            'configletList': c_keys_to_add,
            'configletNamesList': c_names_to_add,
            'ignoreConfigletNamesList': c_names_to_remove,
            'ignoreConfigletList': c_keys_to_remove,
            'configletBuilderList': b_keys_to_add,
            'configletBuilderNamesList': b_names_to_add,
            'ignoreConfigletBuilderList': b_keys_to_remove,
            'ignoreConfigletBuilderNamesList': b_names_to_remove,
            'toId': device['systemMacAddress'],
            'toIdType': 'netelement',
            'fromId': '',
            'nodeName': '',
            'fromName': '',
            'toName': device['fqdn'],
            'nodeIpAddress': device['ipAddress'],
            # test with IP address change
            'nodeTargetIpAddress': device['ipAddress'],
            'childTasks': [],
            'parentTask': ''
        }
        self.addTempTask(task_d, info)

    def addTempAction(self):
        if len(self.temp_task_list):
            url = self.cvp_url_prefix + \
                '/cvpservice/provisioning/addTempAction.do?nodeId=root&format=topology'
            payload = {'data': self.temp_task_list}
            headers = {'content-type': "application/json", }
            resp = self.session.post(url, data=json.dumps(
                payload), headers=headers, timeout=self.timeout)
            self.handle_errors(
                resp, task_description='Trying to add temp tasks to CVP')
            self.temp_task_list = list()  # clean temp task list

    def save_topology(self):
        url = self.cvp_url_prefix + '/cvpservice/provisioning/v2/saveTopology.do'
        resp = self.session.post(
            url, data=json.dumps([]), timeout=self.timeout)
        self.handle_errors(resp, task_description='Saving topology')

    def delete_configlets(self, configlet_list):
        url = self.cvp_url_prefix + '/cvpservice/configlet/deleteConfiglet.do'
        configlets_to_delete = list()
        for configlet in configlet_list:
            d = {'name': configlet['name'], 'key': configlet['key']}
            configlets_to_delete.append(d)
        resp = self.session.post(url, data=json.dumps(
            configlets_to_delete), timeout=self.timeout)
        self.handle_errors(resp, task_description='Deleting configlets')

    def get_tasks(self, query_param='Pending'):
        url = self.cvp_url_prefix + \
            '/cvpservice/task/getTasks.do?queryparam=%s&startIndex=0&endIndex=0' % query_param
        resp = self.session.get(url, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Checking for existing tasks.')

        d = {
            'total': resp.json()['total'],
            'data': resp.json()['data']
        }

        return d

    def execute_tasks(self, task_id_list):
        url = self.cvp_url_prefix + '/cvpservice/task/executeTask.do'
        payload = {'data': task_id_list}
        headers = {'content-type': "application/json", }
        resp = self.session.post(url, data=json.dumps(
            payload), headers=headers, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Trying to add temp tasks to CVP')

    def device_is_compliant(self, device_id):
        url = self.cvp_url_prefix + '/cvpservice/provisioning/checkCompliance.do'
        d = {'nodeId': device_id, 'nodeType': 'netelement'}
        resp = self.session.post(url, data=json.dumps(d), timeout=self.timeout)
        self.handle_errors(resp, task_description='Deleting configlets')
        if resp.json()['complianceCode'] != '0000':
            return False  # not compliant
        else:
            return True  # compliant

    def add_configlet(self, configlet_name, config):
        url = self.cvp_url_prefix + '/cvpservice/configlet/addConfiglet.do'
        payload = {'name': configlet_name, 'config': config}
        headers = {'content-type': "application/json", }
        resp = self.session.post(url, data=json.dumps(
            payload), headers=headers, timeout=self.timeout)
        self.handle_errors(
            resp, task_description='Add configlet %s' % configlet_name)


def load_yaml_file(filename, load_all=False):
    with open(filename, mode='r') as f:
        if not load_all:
            yaml_data = yaml.load(f, Loader=yaml.FullLoader)
        else:
            # convert generator to list before returning
            yaml_data = list(yaml.load_all(f, Loader=yaml.FullLoader))
    return yaml_data


if __name__ == "__main__":

    try:
        with open('upload-configlet-settings.yml', mode='r') as f:
            settings = yaml.load(f, Loader=yaml.FullLoader)
    except Exception as _:
        sys.exit('ERROR: can not load settings file!')
    else:
        cvp_url_prefix = settings['cvp_url_prefix']
        cvp_user = settings['cvp_user']
        cvp_password = settings['cvp_password']
        configlet_directories = settings['configlet_directories']

        cvp_api = CVP(cvp_url_prefix, cvp_user, cvp_password)

        # get device inventory and sort by hostname (only works if hostnames already defined)
        print('Loading device inventory...')
        device_inventory = dict()
        for device_details in cvp_api.get_devices().values():
            device_inventory.update({
                device_details['hostname']: device_details
            })

        # unassign all configlets assigned devices
        configlet_names_to_delete = list()
        for device_hostname, device_details in device_inventory.items():
            configlets_assigned_to_device = cvp_api.get_configlets_for_a_device(
                device_inventory[device_hostname]['systemMacAddress'])
            for old_configlet in configlets_assigned_to_device:
                if old_configlet['name'] not in configlet_names_to_delete:
                    configlet_names_to_delete.append(old_configlet['name'])
            print(f'Unassign configlet from {device_hostname}')
            cvp_api.reassign_configlets_to_device(
                device_details, configlets_assigned_to_device, [])
        print('Creating temp actions')
        cvp_api.addTempAction()  # create temp actions on CVP
        cvp_api.save_topology()  # save topology

        # get configlet inventory and sort by configlet name
        print('Loading configlet inventory')
        configlet_inventory = dict()
        for configlet_details in cvp_api.get_configlets().values():
            configlet_inventory.update({
                configlet_details['name']: configlet_details
            })

        # delete all configlets assigned to devices
        configlets_to_delete = [configlet_inventory[configlet_name]
                                for configlet_name in configlet_names_to_delete]
        print('Deleing configlets')
        cvp_api.delete_configlets(configlets_to_delete)

        # create configlets and define sequence based on directory order
        configlet_name_sequence = list()
        for dir_name in configlet_directories:
            for filename in os.listdir(dir_name):
                configlet_name = filename.split('.')[0]
                configlet_name_sequence.append(configlet_name)
                fp = os.path.join(dir_name, filename)
                with open(fp, 'r') as configlet_text:
                    config = ''.join(configlet_text)
                    print(f'Creating configlet {configlet_name}')
                    cvp_api.add_configlet(configlet_name, config)

        # get configlet inventory and sort by configlet name
        print('Loading configlet inventory')
        configlet_inventory = dict()
        for configlet_details in cvp_api.get_configlets().values():
            configlet_inventory.update({
                configlet_details['name']: configlet_details
            })

        # find configlets that must be assigned to all devices
        shared_configlet_names = list()
        for configlet_name in configlet_inventory.keys():
            is_shared = True
            for device_name in device_inventory.keys():
                if device_name in configlet_name:
                    is_shared = False
            if is_shared:
                shared_configlet_names.append(configlet_name)

        # assign configlets
        for device_hostname, device_details in device_inventory.items():
            device_configlets = list()
            for configlet_name in configlet_name_sequence:  # walk over configlets in original sequence
                if configlet_name in shared_configlet_names:
                    device_configlets.append(
                        configlet_inventory[configlet_name])
                elif device_hostname in configlet_name:
                    device_configlets.append(
                        configlet_inventory[configlet_name])
            print(f'Assigning configlets to {device_hostname}')
            cvp_api.reassign_configlets_to_device(
                device_details, [], device_configlets)
        cvp_api.addTempAction()  # create temp actions on CVP
        cvp_api.save_topology()  # save topology
