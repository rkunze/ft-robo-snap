"""The RoboWeb protocol"""
import inspect

import sys

from ftrobopy import ftrobopy
from ftrobopy.ftrobopy import ftTXT


class Message:
    """Base class for all RoboWeb protocol messages"""


class Request(Message):
    """Base class for RoboWeb protocol requests to the controller"""

    @classmethod
    def from_dict(cls, data):
        """
        Construct a Request instance from *data*

        :type data: dict
        :raises: ValueError if *data* does not represent a RoboWeb protocol Request message
        """
        if not data:
            return Status({})
        elif 'request' in data:
            name = data['request'].lower()
            if name in requests_by_name:
                return requests_by_name[name](data)
            else:
                raise ValueError('Unknown request type: %s' % data['request'])
        else:
            raise ValueError('Not a valid Request message: %s' % data)

    def __init__(self, data):
        self.data = data

    def execute(self, connection):
        pass


class Status(Request):
    """
    Request the current status from the controller.

    Reply is a StatusReport.
    """

    def execute(self, robotxt):
        name_raw, version_raw = robotxt.queryStatus();
        name = name_raw.strip(u'\u0000')
        version = str((version_raw >> 24) & 0xff)
        version += '.' + str((version_raw >> 16) & 0xff)
        version += '.' + str((version_raw >> 8) & 0xff)
        version += '.' + str(version_raw & 0xff)
        return StatusReport(name, version, robotxt.isOnline())


class Configure(Request):
    """
    Request a configuration change from the controller.

    A configuration change request can include the following parameters:

    *mode*
        changes the controller mode. Allowed values are *online* and *offline*.
    *M1/O1+O2* .. *M4/O7+O8*
        configures the corresponding motor/output pins. Allowed values are either "motor"
        (output pins are used for motor control), "output" (the output pins are
        used as individual outputs) or "unused"
    *I1* .. *I8*
        configures the corresponding input. Allowed values are either

        - "unused": the input is not used
        - "digital": the input measures a boolean (on/off) state, e.g. from a connected switch,
        - "resistance", "resistance (5k)": the input measures electrical resistances up to 5 kOhm
        - "resistance (15k)": the input measures electrical resistance up to 15kOhm
        - "voltage": the input measures voltages in the range from 0 to 10 V
        - "distance", "distance (ultrasonic)": the input measures distances in the range of 2 to 1023 cm if a
          Fischertechnik Robo TX ultrasonic distance sensor is connected to the input.

    *default*
        defines the default state for inputs or outputs that are not explicitly set in this
        configuration request. Allowed values are "unused" (resets everything that is not present
        in this configuration request) and "unchanged" (keeps the existing configuration for everything that is not
        explicitly configured in this request). If not set, *default* defaults to "unchanged"

    The controller replies to a configuration change request with either a ConfigurationReport or
    an Error message
    """

    def execute(self, connection):
        keep_old_config = True
        if 'default' in self.data:
            if self.data['default'] == 'unchanged':
                keep_old_config = True
            elif self.data['default'] == 'unused':
                keep_old_config = False
            else:
                return Error('Unsupported default: %s' % self.data['default'])
        try:
            new_config = IOConf(self.data)
        except ConfigError as e:
            return Error(e.message, e.details)
        if 'mode' in self.data:
            if self.data['mode'] == 'online':
                connection.startOnline()
            elif self.data['mode'] == 'offline':
                connection.stopOnline()
            else:
                return Error('Unsupported mode: %s' % self.data['mode'])
        if keep_old_config:
            connection.config.merge(new_config)
        else:
            connection.config = new_config
        connection.setConfig(connection.config.ftTXT_output_conf(), connection.config.ftTXT_input_conf())
        if connection._is_online:
            connection.updateConfig()
        return ConfigurationReport(connection._is_online, connection.config)



class Response(Message, dict):
    """Base class for RoboWeb protocol responses from the controller"""


class Error(Response):
    """
    An error response from the controller

    The error response contains a short error message as **error**, and optionally additional details in **details**
    """

    def __init__(self, message, details=None):
        super(Error, self).__init__()
        self['error'] = message
        if not details is None:
            self['details'] = details


class StatusReport(Response):
    """
    A status report from the controller.

    The status report contains the controller name as **name**, the firmware version as **version**,
    and the current mode (*online* or *offline*) as **mode**
    """

    def __init__(self, name, version, online):
        super(StatusReport, self).__init__()
        self['name'] = name
        self['version'] = version
        self['mode'] = 'online' if online else 'offline'


class ConfigurationReport(Response):
    """
    A configuration report from the controller.

    The configuration report contains the names of all configured motor/output and input pins.
    For motor and output pins, the value is always **active**,
    """

    def __init__(self, is_online, config):
        super(ConfigurationReport, self).__init__()
        self['mode'] = 'online' if is_online else 'offline'
        self.update(config)


class ConfigError(ValueError):
    def __init__(self, message, details):
        super(ConfigError, self).__init__(message, details)
        self.details = details


class IOConf(dict):
    """A glorified dict representing the I/O pin configuration"""
    __input_values_map__ = {
        'unused': (ftTXT.C_SWITCH, ftTXT.C_DIGITAL),  # let unused inputs default to "digital"
        'digital': (ftTXT.C_SWITCH, ftTXT.C_DIGITAL),
        'resistance': (ftTXT.C_RESISTOR, ftTXT.C_ANALOG),
        'resistance (5k)': (ftTXT.C_RESISTOR, ftTXT.C_ANALOG),
        'resistance (15k)': (ftTXT.C_RESISTOR2, ftTXT.C_ANALOG),
        'voltage': (ftTXT.C_VOLTAGE, ftTXT.C_ANALOG),
        'distance': (ftTXT.C_ULTRASONIC, ftTXT.C_ANALOG),
        'distance (ultrasonic)': (ftTXT.C_ULTRASONIC, ftTXT.C_ANALOG)
    }
    __output_values_map__ = {
        'unused' : ftTXT.C_OUTPUT,
        'output' : ftTXT.C_OUTPUT,
        'motor'  : ftTXT.C_MOTOR,
    }
    __input_values__  = frozenset(__input_values_map__.viewkeys())
    __output_values__ = frozenset(__output_values_map__.viewkeys())
    __output_keys__   = ['M1/O1+O2', 'M2/O3+O4', 'M3/O5+O6', 'M4/O7+O8']
    __input_keys__    = ['I' + str(i + 1) for i in range(8)]

    def __init__(self, other=None):
        super(IOConf, self).__init__(self.__check_values__(other))

    @staticmethod
    def __check_values__(data):
        if data is None:
            data = {k: 'unused' for k in IOConf.__input_keys__ + IOConf.__output_keys__}
        elif not (isinstance(data, dict)):
            raise TypeError("Not a dict: %s" % data)
        elif isinstance(data, IOConf):
            return data
        else:
            data = {k: data[k] if k in data else 'unused' for k in IOConf.__input_keys__ + IOConf.__output_keys__}
            illegal_values =  [(k, v) for (k, v) in data.viewitems()
                                 if (k in IOConf.__input_keys__ and not v in IOConf.__input_values__) or
                                    (k in IOConf.__output_keys__ and not v in IOConf.__output_values__)]
            if len(illegal_values) > 0:
                raise ConfigError('Unsupported configuration values', {illegal_values})
        return data

    def ftTXT_output_conf(self):
        return [IOConf.__output_values_map__[self[k]] for k in IOConf.__output_keys__]

    def ftTXT_input_conf(self):
        return [IOConf.__input_values_map__[self[k]] for k in IOConf.__input_keys__]

    def merge(self, other):
        if not isinstance(other, IOConf):
            raise TypeError
        super(IOConf, self).update(other)


class Connection(ftTXT):
    """Represents a connection to a TXT controller"""

    def __init__(self, id, host, port=65000):
        super(Connection, self).__init__(host, port)
        self.id = id
        self.config = IOConf()

    def send(self, request):
        """
        Send *request* to the TXT controller.

        :type request: Request

        :return: The response (if the request causes an immediate response) or None
        :rtype: Response
        :rtype: None
        """
        return request.execute(self)

    def disconnect(self):
        self.stopAll()
        self.stopCameraOnline()
        self.stopOnline()
        active_connections.pop(self.id, None)
        return None


active_connections = {}
requests_by_name = {}
for cls in inspect.getmembers(sys.modules[__name__],
                              lambda cls: inspect.isclass(cls) and issubclass(cls, Request) and not cls is Request):
    requests_by_name[cls[0].lower()] = cls[1]


def connect(client_address, robotxt_address):
    key = str(client_address) + "->" + str(robotxt_address)
    if not key in active_connections:
        connection = Connection(key, robotxt_address)
        active_connections[key] = connection;
    return active_connections[key];
