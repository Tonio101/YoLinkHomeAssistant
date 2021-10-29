import hashlib
import json
import os
import sys

import paho.mqtt.client as mqtt
from logger import Logger
log = Logger.getInstance().getLogger()


class YoLinkMQTTClient(object):
    """
    Object representation for YoLink MQTT Client
    """

    def __init__(self, csid, csseckey, topic, mqtt_url, mqtt_port,
                 device_hash, output_q, client_id=os.getpid()):
        self.csid = csid
        self.csseckey = csseckey
        self.topic = topic
        self.mqtt_url = mqtt_url
        self.mqtt_port = int(mqtt_port)
        self.device_hash = device_hash
        self.output_q = output_q

        self.client = mqtt.Client(client_id=str(__name__ + str(client_id)),
                                  clean_session=True, userdata=None,
                                  protocol=mqtt.MQTTv311, transport="tcp")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        # self.client.tls_set()

    def connect_to_broker(self):
        """
        Connect to MQTT broker
        """
        log.info("Connecting to broker...")

        pwd = hashlib.md5(self.csseckey.encode('utf-8')).hexdigest()
        log.debug(pwd)
        self.client.username_pw_set(username=self.csid,
                                    password=pwd)

        self.client.connect(self.mqtt_url, self.mqtt_port, 10)
        # method blocks the program, handles reconnects, etc.
        # Since we are listening for published messages to the
        # YoLink broker topic, we need to run indefinitely.
        # If you need to do other things, than call loop_start()
        # instead.
        self.client.loop_forever()

    def on_message(self, client, userdata, msg):
        """
        Callback for broker published events
        """
        payload = json.loads(msg.payload.decode("utf-8"))
        # log.debug(payload)
        self.output_q.put(payload)

    def on_connect(self, client, userdata, flags, rc):
        """
        Callback for connection to broker
        """
        log.info("Connected with result code %s" % rc)

        if (rc == 0):
            log.info("Successfully connected to broker %s" % self.mqtt_url)
        else:
            log.error("Connection with result code %s" % rc)
            sys.exit(2)

        self.client.subscribe(self.topic)
