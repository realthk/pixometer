"""Support for Pixometer."""
from datetime import datetime, timedelta
import time
import requests
import threading
import json

import logging
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (CONF_DEVICE_CLASS, CONF_NAME, CONF_PASSWORD,
                                 CONF_USERNAME)
from homeassistant.helpers.entity import Entity

SCAN_INTERVAL = timedelta(minutes=59)
ICON = "mdi:currency-usd"
_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Pixometer Sensor"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Pixometer sensor."""
    username = config[CONF_USERNAME]
    password = config[CONF_PASSWORD]
    wrapper = PixometerWrapper(username, password)

    for meter in wrapper.getMeters():
        add_entities(
            [PixometerSensor(meter, wrapper)])
        _LOGGER.debug("%s sensor added", meter.meter_id)

class PixometerWrapper:
    base_url = "https://pixometer.io/api/v1"

    def __init__(self, username, password):
        self._lock = threading.Lock()
        self._username = username
        self._password = password
        self._lastUpdate = None
        self._meters = None
        self.access_token = None
        self.token_expires = None
        self.updateMeters()

    def getToken(self):
        if self.access_token!=None and self.token_expires>datetime.now():
            _LOGGER.debug('Token is still valid until: ' + str(self.token_expires))
            return True
        postdata = {'username':self._username, 'password': self._password}
        response = requests.post(self.base_url + "/access-token/", data=postdata)
        if not response or not len(response.content):
            _LOGGER.error("Cannot connect to Pixometer")
            return False
        jRes = json.loads(response.content)
        self.access_token = jRes["access_token"]
        self.token_expires = datetime.now() + timedelta(0, jRes["expires_in"])
        self.token_type = jRes["token_type"]
        self.user_id = jRes["user_id"]
        self.headers = {'Authorization' : self.token_type + ' ' + self.access_token}
        _LOGGER.debug('Token expires: ' + str(self.token_expires))
        return True

    def getMeters(self):
        if (self._meters == None):
            self.updateMeters()
        return self._meters

    def clearReadings(self):
        for m in self._meters:
            m.readings.clear()

    def getReadings(self, num=10):
        if self._lastUpdate!=None and self._lastUpdate+SCAN_INTERVAL>datetime.now():
            _LOGGER.debug('Last reading was recently ('+str(self._lastUpdate)+')')
            return True
        if not self.getToken():
            return False
        get_params = {'page_size': num}
        response = requests.get(self.base_url+"/readings/", headers=self.headers, params=get_params)
        if not response or not len(response.content):
            _LOGGER.error("Cannot get readings from Pixometer")
            return False
        self._lastUpdate = datetime.now()
        jRes = json.loads(response.content)
        count = jRes['count']
        if count>0:
            self.clearReadings()
            for r in jRes['results']:
                reading = Reading(r)
                for m in self._meters:
                    if reading.meter==m.url:
                        m.readings.append(reading)

            for m in self._meters:
                if len(m.readings)>0:
                    _LOGGER.debug(m.meter_id+": "+m.readings[0].reading_date+": "+m.readings[0].value)
        else:
            _LOGGER.warning("No readings data from Pixometer")
        return True

    def updateMeters(self):
        self.getToken()
        self._meters = []
        response = requests.get(self.base_url + "/meters/", headers=self.headers)
        if not response or not len(response.content):
            _LOGGER.error("Cannot get meters data from Pixometer")
            return False
        jRes = json.loads(response.content)
        if jRes['count']>0:
            for meter_data in jRes['results']:
                me = Meter(meter_data)
                self._meters.append(me)
                _LOGGER.debug("Found meter " + me.meter_id)
        else:
            _LOGGER.warning("No meters from Pixometer")

class Meter:
    '''
        url => https://pixometer.io/api/v1/meters/xxxxxxx/
        owner => xxx@xxxxxxx.xx
        changed_hash => 9999999999999999999999999999999
        created => 2018-01-21T12:50:19.127Z
        modified => 2019-10-30T12:13:58.886Z
        appearance => mechanical_black
        fraction_digits => 1
        is_double_tariff => False
        location_in_building => Röszke
        meter_id => Áram
        physical_medium => electricity
        physical_unit => kWh
        integer_digits => 6
        register_order => None
        city => None
        zip_code => None
        address => None
        description => None
        label => None
        resource_id => 999999
    '''
    def __init__(self, data):
        self.readings = []
        for key, value in data.items():
            setattr(self, key, value)

class Reading:
    def __init__(self, data):
        for d in ['resource_id', 'reading_date', 'value', 'meter' ]:
            setattr(self, d, data[d])


class PixometerSensor(Entity):
    def __init__(self, meter, wrapper):
        """Initialize the Pixometer sensor."""
        #super().__init__(wrapper)
        self._meter = meter
        self._state = None
        self._wrapper = wrapper
        self._attributes = {}
        self._data = {}
        self._icon = None
        self._device_class = None
        self._unit = None
        self.update()

    @property
    def name(self):
        """Return the name of the sensor."""
        return f'pixometer_{self._meter.meter_id}'

    @property
    def unique_id(self):
        """Return the unique_id of the sensor."""
        return f'pixometer_{self._meter.meter_id}'

    @property
    def available(self) -> bool:
        """Return true if the device is available and value has not expired."""
        return self._state != None

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return self._attributes

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        if self._meter.physical_unit=="m^3":
            return "m³"
        return self._meter.physical_unit

    @property
    def device_class(self):
        """Return device_class based on unit of measurement."""
        if self._meter.physical_unit=="kWh":
            return "energy"
        return None

    @property
    def icon(self):
        """Return icon based on physical_medium."""
        return self._icon

    def update(self):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """
        _LOGGER.debug(f"Updating pixometer sensor {self._meter.meter_id}.")
        self._wrapper.getReadings()
        if len(self._meter.readings):
            self._state = self._meter.readings[0].value

            """Set icon based on physical_medium."""
            if self._meter.physical_medium=="electricity":
                self._icon = "mdi:flash"
                self._device_class = "energy"
                self._unit = "kWh"
            if self._meter.physical_medium=="gas":
                self._icon = "mdi:radiator"
                self._device_class = "gas"
                self._unit = "m³"
            if self._meter.physical_medium=="water":
                self._icon = "mdi:water-pump"
                self._device_class = "gas"
                self._unit = "m³"

            self._attributes = {
                'last_reading'      : self._meter.readings[0].reading_date,
                'appereance'        : self._meter.appearance,
                'physical_medium'   : self._meter.physical_medium,
                'created'           : self._meter.created,
                'state_class'       : 'total_increasing',
                'device_class'      : self._device_class,
                'native_unit_of_measurement' : self._unit,
                }
            if self._meter.label!=None:
                self._attributes['label']=self._meter.label
            if self._meter.zip_code!=None:
                self._attributes['zip_code']=self._meter.zip_code
            if self._meter.city!=None:
                self._attributes['city']=self._meter.city
            if self._meter.address!=None:
                self._attributes['address']=self._meter.address
            if self._meter.location_in_building!=None:
                self._attributes['location_in_building']=self._meter.location_in_building
