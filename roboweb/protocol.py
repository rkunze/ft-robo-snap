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
            return GenericStatusReport(True)
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


class Report(Request):
    """
    Request the current status from the controller.

    A status request can include the following entries:

    ``report`` (optional)
        the name (or a list of names) for status entries that should be included in the reply. Allowed
        values are all valid status reply entry names.

    The reply is either a Status with all entries requested in ``report`` or an Error
    """

    def execute(self, connection):
        if 'include' not in self.data:
            return GenericStatusReport(True);
        includes = self.data['include']
        requested_reports = frozenset([includes] if isinstance(includes, str) else includes)
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


class Out(Request):
    """
    Change settings for one or more motors/outputs

    a set outputs request may include the entries

    ``O1`` .. ``O8``
        Settings for output pins configured as individual outputs. The value for each entry is the PWM setting for this
        entry as an integer in the range 0 .. 512. 0 means "off".
    ``M1`` .. ``M4``
        Settings for output pins that are currently configured as motors. Each entry may contain the sub entries

        * ``speed``: The motor speed (or more correctly, the PWM setting). Values are integers,
          allowed range is -512 .. 512. A value of 0 means "stop". Negative values change the motor direction.
          Out-of-range values will be automatically clamped to the nearest acceptable value.
        * ``steps``: The motor will be stopped after ``steps`` counter ticks on the "fast counter" input
          with the same number as the motor (e.g. *C1* for motor *M1*). Allowed values are non-negative
          integers, a value of 0 (or omitting the ``steps`` parameter) means "run until stopped by another request"
        * ``syncto``: Synchronizes the motor to another motor, i.e. makes both motors run at the same speed and for
          the same number of steps. Allowed values are all motor ids, synchronizing a motor to itself has no effect.

        alternatively, the value of a motor setting may be an int in the range of -512 .. 512 - this is equivalent
        to ``{ "speed" : ... }``

    Example: With two encoder motors connected to M1/C1 and M2/C2 respectively, and a LED connected to O7, the request::

    { "request" : "out", "M1": { "speed" : -512, "steps" : 100, "syncto" : "M2" }, "O7": 255}

    will switch the LED on at (roughly) half power, synchronize motor M2 to M1, and run both motors
    backwards at full speed for 100 encoder steps.

    If some of the requested configuration changes cannot be executed because the corresponding output/motor
    is not configured for this connection), the controller will reply with error messages of the form::

    { "reply": "error", "message" : "set failed", "details" : { "id" : "M1", "reason" : "not configured" }}

    There will be one reply for every unconfigured output.

    For successful output settings, the controller will only send status replies if the client has already requested
    to be notified on status changes for the corresponding output/motor.
    """

    def _set_motor(self, motor, connection, controller):
        idx = connection.config.get(motor, None)
        if idx is None:
            connection.answer(Error('set failed', { 'id': motor, 'reason' : 'not configured'}))
        else:
            values = self.data[motor]
            if isinstance(values, dict):
                speed = values.get('speed')
                syncto_id = values.get('syncto')
                syncto = connection.config.get(syncto_id)
                steps = values.get('steps')
                if not (isinstance(speed, int) and isinstance(steps, int)):
                    return Error('set failed', {'id': motor, 'reason': 'invalid data: %s' % repr(values)})
                if syncto is None and syncto_id is not None:
                    return Error('set failed', {'id': motor, 'reason': 'invalid syncto target: %s' % repr(syncto)})
            elif isinstance(values, int):
                speed = values
                syncto = None
                steps = None
            else:
                return Error('set failed', {'id': motor, 'reason': 'invalid data: %s' % repr(values)})
            speed = _clamp(speed, -512, 512)
            steps = _clamp(steps, 0, 65535)
            if syncto is not None:
                controller.setMotorSyncMaster(idx, syncto+1)
                controller.setMotorSyncMaster(syncto, idx+1)
            if steps is not None:
                controller.setMotorDistance(idx, steps)
            if (syncto is not None) or (steps is not None):
                controller.incrMotorCmdId(idx)
            if speed >= 0:
                 controller.setPwm(idx*2, speed)
                 controller.setPwm(idx*2+1, 0)
            else:
                 controller.setPwm(idx*2, 0)
                 controller.setPwm(idx*2+1, -speed)
        return None

    def _set_output(self, output, connection, controller):
        idx = connection.config.get(output)
        if idx is None:
            return Error('set failed', { 'id': output, 'reason' : 'not configured'})
        value = self.data[output]
        if not isinstance(value, int):
            return Error('set failed', {'id': output, 'reason': 'invalid data: %s' % repr(value)})
        controller.setPwm(idx, _clamp(value, 0, 512))
        return None

    def execute(self, connection):
        controller = _connect_controller()
        if not (isinstance(controller, ftTXT) and controller._is_online):
            return controller if isinstance(controller, Error) else Error('set failed', 'controller is not online')
        controller.SyncDataBegin()
        for motor in IOConf.__motor_pin_names__:
            if motor in self.data:
                error = self._set_motor(motor, connection, controller)
                if error is not None:
                    connection.answer(error)
        for output in IOConf.__output_pin_names__:
            if output in self.data:
                error = self._set_output(output, connection, controller)
                if error is not None:
                    connection.answer(error)
        controller.SyncDataEnd()


class Off(Request):
    """
    Set all outputs to "off".

    Sets all outputs to 0 - even those outputs that are not configured for this connection and may be in use by another
    client connected to the controller.

    This request is intended as an emergency off switch. For normal usage, it is recommended to use a standard "out"
    request instead.
    """
    def execute(self, connection):
        controller = _connect_controller()
        if not (isinstance(controller, ftTXT) and controller._is_online):
            return controller if isinstance(controller, Error) else Error('set all to "off" failed', 'controller is not online')
        controller.stopAll()

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
    __output_pin_names__ = ['O' + str(i + 1) for i in range(8)]
    __motor_pin_names__ = ['M' + str(i + 1) for i in range(4)]
    __input_keys__ = ['I' + str(i + 1) for i in range(8)]

    def __init__(self, other=None):
        super(IOConf, self).__init__(self.__check_values__(other))
        for i in range(0, len(IOConf.__output_keys__)):
            v = self.get(self.__output_keys__[i], None)
            if v == 'motor':
                self['M%i' % (i + 1)] = i
            elif v == 'output':
                self['O%i' % (2 * i + 1)] = 2 * i
                self['O%i' % (2 * i + 2)] = 2 * i + 1

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
        report = {k: v for (k, v) in self.viewitems() if v != 'unused' and k in IOConf.__input_keys__}
        report.update({k: 'active' for k in IOConf.__output_pin_names__ if k in self})
        report.update({k: 'active' for k in IOConf.__motor_pin_names__ if k in self})
        return report

    def apply(self, controller):
        controller.setConfig(self.ftTXT_output_conf(), self.ftTXT_input_conf())
        if controller._is_online:
            controller.updateConfig()

    def output_idx(self, key):
        return self['__active_outputs__'].get(key, None)


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

def _clamp(value, min, max):
    return value if min <= value <= max else min if value < min else max

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
    connected = not (isinstance(controller, Error) or (controller is None))
    result = {'state': 'connected' if connected else 'disconnected'}
    if isinstance(controller, ftTXT):
        result['mode'] = 'online' if controller._is_online else 'offline'
        if full_report and connected:
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
