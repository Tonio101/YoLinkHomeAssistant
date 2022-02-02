from datetime import datetime
import hashlib
import time
import json
import requests
import sys

from enum import Enum
from logger import Logger
log = Logger.getInstance().getLogger()


class DeviceType(Enum):
    DOOR = 1
    TEMPERATURE = 2
    LEAK = 3
    VIBRATION = 4


class TempType(Enum):
    CELSIUS = 1
    FAHRENHEIT = 2


class DoorEvent(Enum):
    UNKNOWN = -1
    OPEN = 1
    CLOSE = 2


class LeakEvent(Enum):
    UNKNOWN = -1
    DRY = 1
    FULL = 2


class VibrateEvent(Enum):
    UNKNOWN = -1
    NO_VIBRATE = 1
    VIBRATE = 2


DEVICE_TYPE = {
    "DoorSensor": DeviceType.DOOR,
    "THSensor": DeviceType.TEMPERATURE,
    "LeakSensor": DeviceType.LEAK,
    "VibrationSensor": DeviceType.VIBRATION
}

EVENT_STATE = {
    "normal": DoorEvent.UNKNOWN,
    "open": DoorEvent.OPEN,
    "closed": DoorEvent.CLOSE,
    "dry": LeakEvent.DRY,
    "full": LeakEvent.FULL,
    "vibrate": VibrateEvent.VIBRATE
}

DEVICE_TYPE_TO_STR = {
    DeviceType.DOOR: "Door Sensor",
    DeviceType.TEMPERATURE: "Temperature Sensor",
    DeviceType.LEAK: "Leak Sensor",
    DeviceType.VIBRATION: "Vibration Sensor"
}


class YoLinkDeviceApi(object):
    """
    Object representatiaon for YoLink Device API
    """

    def __init__(self, url, csid, csseckey):
        self.url = url
        self.csid = csid
        self.csseckey = csseckey

        self.data = {}
        self.header = {}

    def build_device_api_request_data(self, serial_number):
        """
        Build header + payload to enable sensor API
        """
        self.data["method"] = 'Manage.addYoLinkDevice'
        self.data["time"] = str(int(time.time()))
        self.data["params"] = {'sn': serial_number}
        self.serial_number = serial_number

        self.header['Content-type'] = 'application/json'
        self.header['ktt-ys-brand'] = 'yolink'
        self.header['YS-CSID'] = self.csid

        # MD5(data + csseckey)
        self.header['ys-sec'] = \
            str(hashlib.md5((json.dumps(self.data) +
                self.csseckey).encode('utf-8')).hexdigest())

        log.debug("Header:{0} Data:{1}\n".format(self.header, self.data))

    def enable_device_api(self):
        """
        Send request to enable the device API
        """
        response = requests.post(url=self.url,
                                 data=json.dumps(self.data),
                                 headers=self.header)
        log.debug(response.status_code)

        response = json.loads(response.text)
        log.debug(response)

        if response['code'] != '000000':
            log.error("Failed to enable API response!")
            log.info(response)
            sys.exit(2)

        data = response['data']
        log.info("Successfully enabled device API")
        log.info(("Name: {0}\nDeviceId:{1}\n"
                  "SerialNumber:{2}\nType:{3}\n").format(
                      data['name'],
                      data['deviceId'],
                      self.serial_number,
                      data['type']
                  ))

        return data


class YoLinkDevice(object):
    """
    Object representatiaon for YoLink Device
    """

    def __init__(self, device_data):
        self.id = device_data['deviceId']
        self.name = device_data['name']
        self.type = DEVICE_TYPE[device_data['type']]
        self.uuid = device_data['deviceUDID']
        self.token = device_data['token']
        self.raw_type = device_data['type']

        # Device data from each MQTT event received
        # from YoLink brokers
        self.event_payload = {}

        # MQTT server to publish each device
        # data to particular topic
        self.mqtt_server = None
        self.topic = None

    def get_id(self):
        return self.id

    def set_name(self, name):
        self.name = name

    def get_name(self):
        return self.name

    def get_type(self):
        return self.type

    def get_raw_type(self):
        return self.raw_type

    def get_uuid(self):
        return self.uuid

    def get_token(self):
        return self.token

    def refresh_device_data(self, data):
        self.event_payload = data

    def get_device_event(self):
        return self.event_payload['event']

    def get_device_event_time(self):
        return datetime.fromtimestamp(
                self.event_payload['time'] / 1000)\
                .strftime("%Y-%m-%d %H:%M:%S")

    def get_current_time(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_device_message_id(self):
        return self.event_payload['msgid']

    def get_device_data(self):
        return self.event_payload['data']

    def set_mqtt_server(self, mqtt_server):
        self.topic = "yolink/{0}/{1}/report".format(
            self.get_raw_type(),
            self.get_id()
        )
        log.debug(self.topic)
        log.debug(self.get_name())

        self.mqtt_server = mqtt_server

    def set_influxdb_client(self):
        raise NotImplementedError

    def process(self):
        raise NotImplementedError

    def __str__(self):
        to_str = ("Id: {0}\nName: {1}\nType: {2}\n"
                  "Event: {3}\nToken: {4}\n"
                  "Event Time: {5}\nCurrent Time: {6}\n").format(
                      self.id,
                      self.name,
                      DEVICE_TYPE_TO_STR[self.type],
                      self.get_device_event(),
                      self.token,
                      self.get_device_event_time(),
                      self.get_current_time()
        )
        return to_str


class YoLinkDoorDevice(YoLinkDevice):
    """
    Object representatiaon for YoLink Door Sensor
    """

    def __init__(self, device_data):
        super().__init__(device_data)
        self.influxdb_client = None

    def is_open(self):
        return EVENT_STATE[self.get_device_data()['state']] == DoorEvent.OPEN

    def is_close(self):
        return EVENT_STATE[self.get_device_data()['state']] == DoorEvent.CLOSE

    def get_event(self):
        return str(EVENT_STATE[self.get_device_data()['state']])

    def __str__(self):
        to_str = ("Event: {0} ({1}) \n").format(
            self.get_event(),
            self.get_device_data()['state']
        )
        return super().__str__() + to_str

    def set_influxdb_client(self, influxdb_c):
        self.influxdb_client = influxdb_c

    def process(self):
        return self.mqtt_server.publish(self.topic, self.get_event())


class YoLinkTempDevice(YoLinkDevice):
    """
    Object representatiaon for YoLink Temperature Sensor
    """

    def __init__(self, device_data):
        super().__init__(device_data)
        self.temp = 0.0
        self.influxdb_client = None

    def get_temperature(self, type=TempType.FAHRENHEIT):
        self.temp = float(self.get_device_data()['temperature'])

        if type == TempType.FAHRENHEIT:
            return round(((self.temp * 1.8) + 32), 2)

        return round(self.temp, 2)

    def get_humidity(self):
        return round(float(self.get_device_data()['humidity']), 2)

    def set_influxdb_client(self, influxdb_c):
        self.influxdb_client = influxdb_c

    def influxdb_write_data(self):
        if not self.influxdb_client:
            log.debug("InfluxDB client not configured")
            return -1

        return self.influxdb_client.write_data(
                    ("temperature={0},humidity={1}").format(
                        str(self.get_temperature()),
                        str(self.get_humidity())
                    ))

    def __str__(self):
        to_str = ("Temperature (F): {0}\nHumidity: {1}\n").format(
            self.get_temperature(),
            self.get_humidity()
        )
        return super().__str__() + to_str

    def process(self):
        log.debug(("{0} {1}").format(
            self.get_temperature(),
            self.get_humidity()
        ))

        return self.influxdb_write_data()


class YoLinkLeakDevice(YoLinkDevice):
    """
    Object representation for a YoLink Leak Sensor
    """
    def __init__(self, device_data):
        super().__init__(device_data)
        self.curr_state = LeakEvent.FULL
        self.prev_dry_time = 0
        self.influxdb_client = None

    def is_water_exhausted(self):
        return EVENT_STATE[self.get_device_data()['state']] == LeakEvent.DRY

    def is_water_full(self):
        return EVENT_STATE[self.get_device_data()['state']] == LeakEvent.FULL

    def get_state(self):
        if 'state' in self.get_device_data():
            return EVENT_STATE[self.get_device_data()['state']]
        return ''

    def __str__(self):
        to_str = ("Current State: {0}\n").format(
            str(self.get_state())
        )

        return super().__str__() + to_str

    def set_influxdb_client(self, influxdb_c):
        self.influxdb_client = influxdb_c

    def influxdb_write_data(self, data):
        if not self.influxdb_client:
            log.debug("InfluxDB client not configured")
            return -1

        return self.influxdb_client.write_data(data)

    def process(self):
        ret = 0

        if self.get_device_event() == 'LeakSensor.setInterval':
            log.info("Alert interval event, discard")
            return ret
        elif 'state' not in self.get_device_data():
            log.info("State not in device data {0}".format(
                self.get_device_data()
            ))
            return ret

        leak_state = self.get_state()

        if self.curr_state == LeakEvent.FULL:
            if leak_state == LeakEvent.DRY:
                log.info("Toilet Flush! {0}".format(
                    self.get_name()
                ))
                self.influxdb_write_data(data="flush=1")
                self.prev_dry_time = datetime.now()
                self.curr_state = leak_state
            elif leak_state == LeakEvent.FULL:
                self.influxdb_write_data(data="flush=0")
                self.curr_state = leak_state
        elif self.curr_state == LeakEvent.DRY:
            if leak_state == LeakEvent.DRY:
                if self.prev_dry_time != 0:
                    curr_dry_time = datetime.now()
                    if int(curr_dry_time - self.prev_dry_time).seconds >= 30:
                        # Leak or plug is not working correctly
                        log.info("Possible leak detected, notify")
                        self.influxdb_write_data(data="flush=1")
                        ret = self.mqtt_server.publish(
                                    self.topic, "LeakDetected")
                    self.prev_dry_time = curr_dry_time
            elif leak_state == LeakEvent.FULL:
                log.info("Toilet [{0}] Water Back To Normal".format(
                    self.get_name()
                ))
                self.influxdb_write_data(data="flush=0")
                self.prev_dry_time = 0
                self.curr_state = leak_state

        # return self.mqtt_server.publish(self.topic, self.get_event())
        return ret


class YoLinkVibrationDevice(YoLinkDevice):
    """
    Object representation for a YoLink Vibration Sensor
    """
    def __init__(self, device_data, name=''):
        super().__init__(device_data)
        super().set_name(name)
        self.curr_state = VibrateEvent.NO_VIBRATE
        self.vibrate_count = 0

    def is_vibrating(self):
        return (self.get_device_data()['state'] == 'alert')

    def get_state(self):
        if 'state' in self.get_device_data():
            if self.is_vibrating():
                return VibrateEvent.VIBRATE
        return VibrateEvent.NO_VIBRATE

    def __str__(self):
        to_str = ("Current State: {0}\n").format(
            str(self.get_state())
        )

        return super().__str__() + to_str

    def process(self):
        ret = 0

        if 'state' not in self.get_device_data():
            log.info("State not in device data {0}".format(
                self.get_device_data()
            ))
            return ret

        vibrate_state = self.get_state()

        if self.curr_state == VibrateEvent.NO_VIBRATE:
            if vibrate_state == VibrateEvent.VIBRATE:
                self.vibrate_count += 1
                log.info("{} vibration detection!".format(
                    self.get_name()
                ))
            elif vibrate_state == VibrateEvent.NO_VIBRATE:
                self.vibrate_count = 0
                log.info("No {} vibration".format(
                    self.get_name()
                ))
            self.curr_state = vibrate_state
        elif self.curr_state == VibrateEvent.VIBRATE:
            if vibrate_state == VibrateEvent.NO_VIBRATE:
                log.info("{} vibration stopped, current count: {}".format(
                    self.get_name(),
                    self.vibrate_count
                ))
                if self.get_device_event() == 'VibrationSensor.StatusChange' \
                   and self.vibrate_count >= 15:
                    log.info("Notify that {} is done [{}]".format(
                        self.get_name(),
                        self.vibrate_count
                    ))
                    self.mqtt_server.publish(
                        self.topic,
                        "{} Finished".format(
                            self.get_name()
                        )
                    )
                    self.vibrate_count = 0
            elif vibrate_state == VibrateEvent.VIBRATE:
                self.vibrate_count += 1
                log.info("{} still working [{}]".format(
                    self.get_name(),
                    self.vibrate_count
                ))
            self.curr_state = vibrate_state

        return ret
