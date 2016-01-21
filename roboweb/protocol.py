"""The RoboWeb protocol"""
import inspect
import random

import sys

from ftrobopy import ftrobopy
from ftrobopy.ftrobopy import ftTXT

robotxt_address = 'localhost'


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
            if name in _requests_by_name:
                return _requests_by_name[name](data)
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

    A status request can include the following entries:

    ``report`` (optional)
        the name (or a list of names) for status entries that should be included in the reply. Allowed
        values are all valid status reply entry names.

    The reply is either a Status with all entries requested in ``report`` or an Error
    """

    def execute(self):
        if 'report' not in self.data:
            return Status();
        requested_reports = frozenset(self['report'])
        reports = {}
        controller = _connect_controller()
        if 'controller' in requested_reports:
            reports['controller'] = _controller_state(controller, full_report=True)
        if not isinstance(controller, Error):
            pass  # TODO: Implement this
        elif len(requested_reports) > (1 if 'controller' in requested_reports else 0):
            return Error("Controller not connected, cannot report status for %s" % ', '.join(requested_reports),
                         controller)
        return Status(**reports)


class Configure(Request):
    """
    Request a configuration change from the controller.

    A configuration change request can include the following entries (all optional):

    ``mode``
        changes the controller mode. Allowed values are "online" and "offline".
    ``M1/O1,O2`` .. ``M4/O7,O8``
        configures the corresponding motor/output pins. Allowed values are either "motor"
        (output pins are used for motor control), "output" (the output pins are
        used as individual outputs) or "unused"
    ``I1`` .. ``I8``
        configures the corresponding input. Allowed values are either

        - "unused": the input is not used
        - "digital": the input measures a boolean (on/off) state, e.g. from a connected switch,
        - "resistance", "resistance (5k)": the input measures electrical resistances up to 5 kOhm
        - "resistance (15k)": the input measures electrical resistance up to 15kOhm
        - "voltage": the input measures voltages in the range from 0 to 10 V
        - "distance", "distance (ultrasonic)": the input measures distances in the range of 2 to 1023 cm if a
          Fischertechnik Robo TX ultrasonic distance sensor is connected to the input.

    ``default``
        defines the default state for inputs or outputs that are not explicitly set in this
        configuration request. Allowed values are "unused" (resets everything that is not present
        in this configuration request) and "unchanged" (keeps the existing configuration for everything that is not
        explicitly configured in this request). If not set, *default* defaults to "unchanged"

    The reply is either a Status that includes a ``configuration`` and a ``controller`` entry or an Error.
    """

    def execute(self, connection):
        keep_old_config = True
        errors = []
        if 'default' in self.data:
            if self.data['default'] == 'unchanged':
                keep_old_config = True
            elif self.data['default'] == 'unused':
                keep_old_config = False
            else:
                errors.append('Unsupported default: %s' % self.data['default'])
        try:
            new_config = IOConf(self.data)
        except ConfigError as e:
            errors.append(e)
            new_config = None

        new_mode = self.data.get('mode', None)
        if new_mode not in ['online', 'offline', None]:
            errors.append('Unsupported mode: %s' % self.data['mode'])
        if new_config is not None:
            if keep_old_config:
                connection.config.merge(new_config)
            else:
                connection.config = new_config
            for other_conn in _active_connections.viewvalues():
                if other_conn != connection:
                    conflicts = other_conn.config.conflicts(new_config)
                    if conflicts:
                        errors.append('Conflicts with settings from connection %s: %s' % (other_conn.id, conflicts))
        if errors:
            return Error('Configuration request failed', errors)
        else:
            controller = _connect_controller()
            if not isinstance(controller, Error):
                if new_mode == 'online':
                    controller.startOnline()
                elif new_mode == 'offline':
                    controller.stopOnline()
                if new_config is not None:
                    _global_io_conf.merge(new_config)
                    _global_io_conf.apply(controller)
                controller_state = {'mode': 'online' if controller._is_online else 'offline'}
            else:
                controller_state = {'state': 'disconnected', 'details': controller}
            return Status(controller=controller_state, configuration=connection.config.report())


class Reply(Message, dict):
    """Base class for RoboWeb protocol replies from the controller"""


class Error(Reply):
    """
    An error reply from the controller.

    An error reply has four entries:

    ``reply``
        the fixed string "error"
    ``message``
        a short string containing an error message
    ``details`` (optional)
        additional information about the error. The ``details`` entry can be any
        data type serializable as JSON

    """

    def __init__(self, message, details=None):
        super(Error, self).__init__(reply='error', error=message, details=details)


class Status(Reply):
    """
    A status reply from the controller.

    The status reply is the main reply type of the RoboWeb protocol - almost all replies have this type.
    A status reply can include the following entries:

    ``reply``
        the fixed string "status"
    ``controller``
        an object describing the controller state with the entries
        * ``state``: the current controller state. Values can be "connected" or "disconnected"
        * ``details``: an object with detailed information why the controller is
            disconnected. Only included if ``state`` is "disconnected",
        * ``mode``: the current controller mode. Values can be "online" or "offline"
        * ``name``: the controller name.
        * ``version``: the controller firmware version.
        * ``connection``: the connection id of the current connection
        All entries are optional, which entries are included depends on the controller state and the
        request that caused this reply
    ``configuration``
        an object describing the current configuration with the following entries:
        * ``mode``: the current controller mode. Values can be "online" or "offline"
        * ``M1`` .. ``M4``: the configurations for all motor pins that are configured (i.e. have not been set to
          "unused"). Value is always "active"
        * ``O1`` .. ``O8``: the configurations for all individual output pins that are configured (i.e. have not
           been set to "unused"). Value is always "active"
        * ``I1`` .. ``I8``: the configurations for all inputs that are configured (i.e. have not
           been set to "unused"). Value is the input type for the pin as set by the last configuration
           request ("digital", "resistance", "voltage", ...)
    All status reply entries except ``reply`` are optional. Which optional entries are included depends on the
    request that caused this reply and on the current configuration of the connection.
    """

    def __init__(self, **kwargs):
        super(Status, self).__init__(reply='status', **kwargs)

class GenericStatusReport(Status):
    """A generic status report with default settings."""

    def __init__(self, verbose=False):
        super(GenericStatusReport, self).__init__(
            controller=_controller_state(_controller, full_report=verbose)
        )


class ConfigError(ValueError):
    def __init__(self, message, details):
        super(ConfigError, self).__init__(message, details)
        self.details = details


class IOConf(dict):
    """A glorified dict representing the I/O pin configuration"""
    __input_values_map__ = {
        'unused': (ftTXT.C_SWITCH, ftTXT.C_DIGITAL),  # unused inputs default to "switch"
        'digital': (ftTXT.C_SWITCH, ftTXT.C_DIGITAL),
        'resistance': (ftTXT.C_RESISTOR, ftTXT.C_ANALOG),
        'resistance (5k)': (ftTXT.C_RESISTOR, ftTXT.C_ANALOG),
        'resistance (15k)': (ftTXT.C_RESISTOR2, ftTXT.C_ANALOG),
        'voltage': (ftTXT.C_VOLTAGE, ftTXT.C_ANALOG),
        'distance': (ftTXT.C_ULTRASONIC, ftTXT.C_ANALOG),
        'distance (ultrasonic)': (ftTXT.C_ULTRASONIC, ftTXT.C_ANALOG)
    }
    __output_values_map__ = {
        'unused': ftTXT.C_OUTPUT,
        'output': ftTXT.C_OUTPUT,
        'motor': ftTXT.C_MOTOR,
    }
    __input_values__ = frozenset(__input_values_map__.viewkeys())
    __output_values__ = frozenset(__output_values_map__.viewkeys())
    __output_keys__ = ['M1/O1,O2', 'M2/O3,O4', 'M3/O5,O6', 'M4/O7,O8']
    __input_keys__ = ['I' + str(i + 1) for i in range(8)]

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
            data = {k: data[k] for k in IOConf.__input_keys__ + IOConf.__output_keys__ if k in data}
            illegal_values = [(k, v) for (k, v) in data.viewitems()
                              if (k in IOConf.__input_keys__ and not v in IOConf.__input_values__) or
                              (k in IOConf.__output_keys__ and not v in IOConf.__output_values__)]
            if len(illegal_values) > 0:
                raise ConfigError('Unsupported configuration values', dict(illegal_values))
        return data

    def ftTXT_output_conf(self):
        return [IOConf.__output_values_map__[self.get(k, 'unused')] for k in IOConf.__output_keys__]

    def ftTXT_input_conf(self):
        return [IOConf.__input_values_map__[self.get(k, 'unused')] for k in IOConf.__input_keys__]

    def conflicts(self, other):
        return {k: (v, self[k])
                for (k, v) in other.viewitems()
                if not (v == 'unused' or self[k] == 'unused' or v == self[k])}

    def merge(self, other):
        if not isinstance(other, IOConf):
            raise TypeError
        super(IOConf, self).update({k: (v if v != 'unused' else self[k]) for (k, v) in other.viewitems()})

    def report(self):
        report = {k: v for (k, v) in self.viewitems() if v != 'unused' and k in self.__input_keys__}
        for i in range(0, len(self.__output_keys__)):
            v = self.get(self.__output_keys__[i], None)
            if v == 'motor':
                report['M%i' % (i + 1)] = 'active'
            elif v == 'output':
                report['O%i' % (2 * i + 1)] = 'active'
                report['O%i' % (2 * i + 2)] = 'active'
        return report

    def apply(self, controller):
        controller.setConfig(self.ftTXT_output_conf(), self.ftTXT_input_conf())
        if controller._is_online:
            controller.updateConfig()


class Connection:
    """Represents a connection to a TXT controller"""

    def __init__(self, connection_id, reply_callback):
        self.id = connection_id
        self.config = IOConf()
        self.answer = reply_callback

    def send(self, request):
        """
        Send *request* to the TXT controller.

        Any reply to the message are sent back over the reply_callback
        :type request: Request

        :rtype: None
        """
        if isinstance(request, Request):
            reply = request.execute(self)
        if reply is not None:
            self.answer(reply)

    def disconnect(self):
        global _controller
        _active_connections.pop(self.id, None)
        if (not _active_connections) and _controller is not None:
            _controller.stopAll()
            _controller.stopCameraOnline()
            _controller.stopOnline()
            _controller = None
        return None


_active_connections = {}
_requests_by_name = {}
_global_io_conf = IOConf()
_controller = None


def _controller_connected():
    return _controller is not None


def _disconnect_controller(message, cause):
    global _controller
    error = Error(message, cause)
    for connection in _active_connections.viewvalues():
        connection.answer(error)
    _controller = None
    return True


def _connect_controller():
    global _controller
    if _controller is None:
        try:
            _controller = ftTXT(robotxt_address, 65000, _disconnect_controller)
        except Exception as err:
            return Error("Connection to TXT controller at %s:65000 failed", err)
        _global_io_conf.apply(_controller)
    return _controller

def _controller_state(controller, full_report=False):
    result = {'state': 'disconnected' if isinstance(controller, Error) or controller is None else 'connected'}
    if isinstance(controller, ftTXT):
        result['mode'] = 'online' if controller._is_online else 'offline'
        if full_report:
            name_raw, version_raw = _controller.queryStatus()
            result['name'] = name_raw.strip(u'\u0000')
            version = str((version_raw >> 24) & 0xff)
            version += '.' + str((version_raw >> 16) & 0xff)
            version += '.' + str((version_raw >> 8) & 0xff)
            version += '.' + str(version_raw & 0xff)
            result['version'] = version
    elif isinstance(controller, Error):
        result['details'] = controller
    return result


def connect(reply_callback, connection_id=None):
    """
    Get a connection to the controller

    If ``connection_id`` is specified and there is an existing active connection with the same
    connection id, the existing connection is returned. Otherwise, a new connection is created,
    either with the given connection_id or with a new, random connection id

    :type reply_callback: (Reply) -> Any
    :param reply_callback: a callback function for sending replies back to the client
    :type connection_id: Connection
    :param connection_id: an arbitrary identifier for the connection (optional)
    :return: a Connection instance
    """
    _connect_controller()
    if connection_id is None:
        connection_id = hex(random.randint(0, 0x10000000))
    key = str(connection_id)
    if key not in _active_connections:
        connection = Connection(connection_id=key, reply_callback=reply_callback)
        _active_connections[key] = connection
    else:
        connection = _active_connections[key]
        connection.answer = reply_callback
    return connection


for cls in inspect.getmembers(sys.modules[__name__],
                              lambda c: inspect.isclass(c) and issubclass(c, Request) and c is not Request):
    _requests_by_name[cls[0].lower()] = cls[1]
