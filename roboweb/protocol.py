"""The RoboWeb protocol"""
import inspect

import sys

from ftrobopy import ftrobopy


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
        self.data = data;

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

    **mode**
        changes the controller mode. Allowed values are *online* and *offline*.
    **M1** .. **M4**
        configures the corresponding motor output pins. Allowed values are either *active*
        (output pins are used for motor control) or *unused* (the output pins are
        available for use as individual outputs)
    **O1** .. **O8**
        configures the corresponding single output pin. Allowed values are either *active*
        (output pin is used as individual output) or *unused* (output pin is available for
        motor control)
    **I1** .. **I8**
        configures the corresponding input. Allowed values are either

        - *unused*: the input is not used
        - *digital*: the input measures a boolean (on/off) state, e.g. from a connected switch,
        - *resistance*: the input measures electrical resistance
        - *voltage*: the input measures voltages
        - *distance*: the input measures distances. Note that this only works if a
          Fischertechnik Robo TX ultrasonic distance sensor is connected to the input.

    **default**
        defines the default state for inputs or outputs that are not explicitly set in this
        configuration request. Allowed values are *unused* (resets everything that is not present
        in this configuration request) and *unchanged* (keeps the existing configuration for everything that is not
        explicitly configured in this request). If not set, **default** defaults to *unchanged*

    The controller replies to a configuration change request with either a ConfigurationReport or
    an Error message
    """


class Response(Message, dict):
    """Base class for RoboWeb protocol responses from the controller"""


class Error(Response):
    """
    An error response from the controller

    The error response contains a short error message as **error**, and optionally additional details in **details**
    """

    def __init__(self, message, details=None):
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
        self['name'] = name
        self['version'] = version
        self['mode'] = 'online' if online else 'offline'


class ConfigurationReport(Response):
    pass


class Connection(ftrobopy.ftTXT):
    """Represents a connection to a TXT controller"""

    def __init__(self, id, host, port=65000):
        super(Connection, self).__init__(host, port)
        self.id = id;

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
for cls in inspect.getmembers(sys.modules[__name__], lambda cls: inspect.isclass(cls) and issubclass(cls, Request) and not cls is Request):
    requests_by_name[cls[0].lower()] = cls[1]


def connect(client_address, robotxt_address):
    key = str(client_address) + "->" + str(robotxt_address)
    if not key in active_connections:
        connection = Connection(key, robotxt_address)
        active_connections[key] = connection;
    return active_connections[key];
