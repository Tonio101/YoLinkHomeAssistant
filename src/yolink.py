#!/usr/bin/env python3

import argparse
import json
import os
import queue
import sys

from time import sleep
from logger import Logger
from logging import DEBUG
from mqtt_client import YoLinkConsumer, MQTTClient
from influxdb_interface import InfluxDbClient
from yolink_devices import YoLinkDeviceApi, YoLinkDoorDevice, \
                           YoLinkLeakDevice, YoLinkTempDevice, \
                           DEVICE_TYPE, DeviceType, YoLinkVibrationDevice
from yolink_mqtt_client import YoLinkMQTTClient
log = Logger.getInstance().getLogger()

Q_SIZE = 16


def parse_config_file(fname):
    """
    Parse configuration file.

    Args:
        fname (string): Config file name.

    Returns:
        dict: JSON converted to a dict.
    """
    with open(os.path.abspath(fname), 'r') as fp:
        data = json.load(fp)
        return data


def yolink_device_init(data):
    """
    Enable the device API on each YoLink device
    and create an object.

    Args:
        data ([type]): [description]

    Raises:
        NotImplementedError: [description]

    Returns:
        [type]: [description]
    """
    yolink_api = YoLinkDeviceApi(data['yoLink']['apiUrl'],
                                 data['yoLink']['csId'],
                                 data['yoLink']['csSecKey'])

    # Need to publish to another broker to distinguish between
    # each of the YoLink devices. All YoLink devices publish
    # to the same topic (CSName/report)
    mqtt_server = \
        MQTTClient(username=data['mqttProducer']['user'],
                   password=data['mqttProducer']['pasw'],
                   mqtt_host=data['mqttProducer']['host'],
                   mqtt_port=data['mqttProducer']['port'])
    mqtt_server.connect_to_broker()

    device_hash = dict()
    yolink_device = None

    for serial_num in data['yoLink']['deviceSerialNumbers']:
        yolink_api.build_device_api_request_data(serial_num['sn'])
        device_data = yolink_api.enable_device_api()

        # Different sensors provide different type of data
        # and the data could be analyzed differently.
        # Hence, add additional sensors as needed here.
        device_type = DEVICE_TYPE[device_data['type']]
        if device_type == DeviceType.DOOR:
            yolink_device = YoLinkDoorDevice(device_data=device_data)
        elif device_type == DeviceType.TEMPERATURE:
            yolink_device = YoLinkTempDevice(device_data=device_data)
        elif device_type == DeviceType.LEAK:
            yolink_device = YoLinkLeakDevice(device_data=device_data)
        elif device_type == DeviceType.VIBRATION:
            yolink_device = \
                YoLinkVibrationDevice(device_data=device_data,
                                      name=serial_num['name'])
        else:
            raise NotImplementedError(("Device {0} is "
                                       "not implemented yet").format(
                                           device_type
                                       ))

        yolink_device.set_mqtt_server(mqtt_server)
        device_hash[yolink_device.get_id()] = yolink_device

    log.debug(device_hash)

    return device_hash


def configure_influxdb_devices(device_hash, data):
    """[summary]

    Args:
        device_hash ([type]): [description]
        data ([type]): [description]
    """
    influxdb_info = data['influxDb']
    if len(influxdb_info['sensors']) == 0:
        log.debug("No sensors are configured for influx db")
        return

    for sensor in influxdb_info['sensors']:
        device_id = sensor['deviceId']
        if device_id in device_hash:
            client = \
                InfluxDbClient(url=influxdb_info['url'],
                               auth=(influxdb_info['auth']['user'],
                                     influxdb_info['auth']['pasw']),
                               db_name=influxdb_info['dbName'],
                               measurement=sensor['measurement'],
                               tag_set=sensor['tagSet'])
            device_hash[device_id].set_influxdb_client(client)


def main(argv):
    usage = ("{FILE} "
             "--config <config_file.yml> "
             "--debug").format(FILE=__file__)
    description = 'Enable Sensor APIs and subscribe to MQTT broker'
    parser = argparse.ArgumentParser(usage=usage, description=description)

    parser.add_argument("-c", "--config", help="Config File",
                        required=True)
    parser.add_argument("-d", "--debug", help="Debug",
                        action='store_true', required=False)

    parser.set_defaults(debug=False)

    args = parser.parse_args()

    if args.debug:
        log.setLevel(DEBUG)

    log.debug("{0}\n".format(args))

    data = parse_config_file(args.config)
    device_hash = yolink_device_init(data)
    configure_influxdb_devices(device_hash, data)

    output_q = queue.Queue(maxsize=Q_SIZE)

    consumer = YoLinkConsumer(name='consumer',
                              args=(output_q, device_hash,))
    consumer.start()
    sleep(2)

    yolink_mqtt_server = \
        YoLinkMQTTClient(csid=data['yoLink']['csId'],
                         csseckey=data['yoLink']['csSecKey'],
                         topic=data['yoLink']['mqtt']['topic'],
                         mqtt_url=data['yoLink']['mqtt']['url'],
                         mqtt_port=data['yoLink']['mqtt']['port'],
                         device_hash=device_hash,
                         output_q=output_q)
    yolink_mqtt_server.connect_to_broker()


if __name__ == '__main__':
    main(sys.argv)
