import sys
import threading
from time import sleep

import paho.mqtt.client as mqtt
from logger import Logger
log = Logger.getInstance().getLogger()


class MQTTClient(object):
    """
    Object representation for a MQTT Client
    """

    def __init__(self, username, password, mqtt_host, mqtt_port):
        self.host = mqtt_host
        self.port = mqtt_port

        self.client = mqtt.Client(client_id=__name__, clean_session=True,
                                  userdata=None, protocol=mqtt.MQTTv311,
                                  transport="tcp")
        self.client.username_pw_set(username, password)
        self.client.on_connect = self.on_connect

    def connect_to_broker(self):
        """
        Connect to MQTT broker
        """
        log.info("Connecting to broker...")
        self.client.connect(self.host, self.port, 10)
        # Spins a thread that will call the loop method at
        # regualr intervals and handle re-connects.
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, rc):
        """
        Callback for broker connection event
        """
        log.info("Connected with result code %s" % rc)

        if (rc == 0):
            log.info("Successfully connected to broker %s" % self.host)
        else:
            log.error("Connection with result code %s" % rc)
            sys.exit(2)

    def publish(self, topic, data):
        """
        Publish events to topic
        """
        rc = self.client.publish(str(topic), data)
        if rc[0] == 0:
            log.debug("Successfully published event to topic {0}".format(
                topic
            ))
        else:
            log.error("Failed to publish {0} to topic {1}".format(
                data, topic
            ))

        return rc[0]


class YoLinkConsumer(threading.Thread):
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, verbose=None):
        super(YoLinkConsumer, self).__init__()
        self.target = target
        self.name = name
        self.output_q = args[0]
        self.device_hash = args[1]

    def run(self):
        while True:
            if not self.output_q.empty():
                payload = self.output_q.get()
                log.debug("Pulled from the output_q")
                log.debug(payload)
                rc = self.process_entry(payload)
                if rc == 0:
                    log.debug(
                        ("Successfully processed entry, number "
                         "of entries in the queue: {0}").format(
                             self.output_q.qsize()
                         ))
                else:
                    log.error("Failed to process entry {0}".format(
                        rc
                    ))
            sleep(0.5)

    def process_entry(self, payload):
        device_id = payload['deviceId']

        if device_id not in self.device_hash:
            log.debug(("Device ID:{0} is not "
                       "in device hash").format(device_id))
            return -1

        self.device_hash[device_id].refresh_device_data(payload)
        device = self.device_hash[device_id]
        log.debug("\n{0}\n".format(device))

        rc = 0
        try:
            rc = device.process()
        except Exception as e:
            log.error(e)
            rc = -1

        return rc
