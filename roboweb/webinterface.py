""" A combined HTTP and WebSocket handler realizing the RoboWeb interface"""
import urlparse
from SimpleHTTPServer import SimpleHTTPRequestHandler

robotxt_address = 'localhost'

from httpwebsockethandler.HTTPWebSocketsHandler import HTTPWebSocketsHandler


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
    with the controller using the RoboWeb protocol (see Protocol.py for details).
    
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
                self._handle_roboweb_message(dict_from_query_string(self.path[9:]))
        else:
            self.send_error(404)

    def do_HEAD(self):
        if is_static_path(self.path):
            SimpleHTTPRequestHandler.do_HEAD(self)
        else:
            self.send_error(405)

    def do_POST(self):
        if is_control_path(self.path):
            type = self.headers.getheader('content-type')
            length = int(self.headers.getheader('content-length'))
            message = self.rfile.read(length)
            if type == 'application/json':
                self._handle_roboweb_message(dict_from_query_string(message))
            elif type == 'application/x-www-form-urlencoded':
                self._handle_roboweb_message(dict_from_query_string(message))
            else:
                self.send_error(415)
        else:
            self.send_error(405)

    def on_ws_message(self, message):
        pass

    def on_ws_connected(self):
        pass

    def on_ws_closed(self):
        pass

    def _handle_roboweb_message(self, param):
        self.send_error(501, 'Not Yet Implemented')


def dict_from_query_string(param):
    pass
