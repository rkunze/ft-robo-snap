""" A combined HTTP and WebSocket handler realizing the RoboWeb interface"""
import json
import urlparse
from BaseHTTPServer import BaseHTTPRequestHandler
from SocketServer import BaseRequestHandler

from roboweb import protocol
from SimpleHTTPServer import SimpleHTTPRequestHandler

from httpwebsockethandler.HTTPWebSocketsHandler import HTTPWebSocketsHandler

robotxt_address = 'localhost'

def is_static_path(path):
    return (path == '/') or (path == '/index.html') or path.startswith('/snap/') or path.startswith('/ui/')


def is_control_path(path):
    return path == '/control' or path.startswith('/control?')


class WebInterfaceHandler(HTTPWebSocketsHandler):
    """
    Handles HTTP and WebSocket requests from clients.

    This handler realizes both the actual web interface to the controller 
    software (either as a WebSocket connection or via HTTP POST/GET) and
    serves static files from selected subdirectories (Only HTTP GET/HEAD 
    allowed).
    
    Allowed static paths are:

    /
        redirects to ``/index.html``
    /index.html
        entry point for the web interface
    /snap/*
        the Snap! IDE (adapted for controlling the Robotics TXT)
    /ui/*
        additional pages and resources (images, style sheets etc.) for the web interface
    
    The actual web interface is located at ``/control`` and allows communication
    with the controller using the RoboWeb protocol (see protocol.py for details).
    
    Messages can be exchanged either by doing a WebSocket handshake on the
    ``/control`` URL and sending/receiving RoboWeb protocol messages encoded in
    JSON, or by sending commands encoded as HTTP parameters via GET/POST.
    
    WebSocket is the preferred method for communication because it has
    less overhead than HTTP and allows the controller to actively push messages
    to the client (e.g to signal input changes), as opposed to HTML where the
    current state must be polled by the client.
    """

    server_version = "RoboWeb/0.1"
    protocol_version = "HTTP/1.1"

    def setup(self):
        HTTPWebSocketsHandler.setup(self)
        self.robotxt_connection = protocol.connect(self.client_address, robotxt_address)


    def list_directory(self, path):
        # we do not allow directory listing.
        self.send_error(403)

    def do_GET(self):
        if is_static_path(self.path):
            SimpleHTTPRequestHandler.do_GET(self)
        elif is_control_path(self.path):
            if self.headers.get("Upgrade", None) == "websocket":
                self._handshake()
                # This handler is in WebSocket mode now.
                # do_GET only returns after client close or socket error.
                self._read_messages()
            else:
                self._handle_roboweb_message_http(self.path[9:], False)
        else:
            self.send_error(404)

    def do_HEAD(self):
        if is_static_path(self.path):
            SimpleHTTPRequestHandler.do_HEAD(self)
        else:
            self.send_error(405)

    def do_POST(self):
        if is_control_path(self.path):
            content_type = self.headers.getheader('content-type')
            length = int(self.headers.getheader('content-length'))
            message = self.rfile.read(length)
            if content_type == 'application/json':
                self._handle_roboweb_message_http(message, True)
            elif content_type == 'application/x-www-form-urlencoded':
                self._handle_roboweb_message_http(message, False)
            else:
                self.send_error(415)
        else:
            self.send_error(405)

    def on_ws_message(self, message):
        pass

    def on_ws_connected(self):
        pass

    def on_ws_closed(self):
        self.robotxt_connection.disconnect()

    def _handle_roboweb_message_http(self, message, is_json = False):
        try:
            parsed = json.loads(message, None, None, protocol.Request.from_dict) if is_json else msg_from_query_string(message)
            response = self.robotxt_connection.send(parsed)
            if response is None:
                # For HTTP, we always want a response, so we fake one
                # if the message did not cause an immediate reply
                response = dict(status = 'OK')
        except ValueError as err:
            response = protocol.Error(err.message)
        except Exception as err:
            self.send_error(500, "Lost connection to the controller: " + err.message)
        data = json.dumps(response)
        self.send_response(200) # Note: protocol errors are not encoded in HTTP status codes
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def send_error(self, code, message=None):
        self.robotxt_connection.disconnect();
        BaseHTTPRequestHandler.send_error(self, code, message)


def msg_from_query_string(message):
    parsed = {}
    for name, value in urlparse.parse_qsl(message):
        value = _to_base_type(value)
        if name in parsed:
            existing = parsed[name]
            if isinstance(existing, list):
                existing.append(value)
            else:
                parsed[name] = [existing, value]
        else:
            parsed[name] = value
    return protocol.Request.from_dict(parsed)

def _to_base_type(value):
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            if value == 'true':
                return True
            elif value == 'false':
                return False
            else:
                return value
