import machine
import network
import socket
import time
import sys
import ubinascii
import struct

# Wi-Fi network credentials
SSID = 'chirana_ext_elektro_2g'
PASSWORD = 'chiranachirana'

# Modbus slave address
slave_address = 1  # Adjust as needed

# Initialize UART for Modbus RTU communication
# Adjust UART number and pins as per your hardware
# For example, on ESP32:
uart = machine.UART(1, tx=machine.Pin(17), rx=machine.Pin(16), baudrate=9600, bits=8, parity=None, stop=1, timeout=1000)

def modbus_crc(data):
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 1):
                crc >>=1
                crc ^= 0xA001
            else:
                crc >>=1
    return crc

def read_holding_registers(slave_addr, start_addr, quantity):
    # Build Modbus frame
    frame = bytearray()
    frame.append(slave_addr)
    frame.append(0x03)  # Function code for Read Holding Registers
    frame.append((start_addr >> 8) & 0xFF)  # Starting address high byte
    frame.append(start_addr & 0xFF)         # Starting address low byte
    frame.append((quantity >> 8) & 0xFF)    # Quantity high byte
    frame.append(quantity & 0xFF)           # Quantity low byte
    crc = modbus_crc(frame)
    frame.append(crc & 0xFF)        # CRC low byte
    frame.append((crc >> 8) & 0xFF) # CRC high byte
    # Send frame
    uart.write(frame)
    time.sleep(0.05)  # Short delay
    # Read response
    response = uart.read(5 + 2 * quantity)
    if response and len(response) >= 5 + 2 * quantity:
        # Check CRC
        resp_crc = response[-2] + (response[-1] << 8)
        calc_crc = modbus_crc(response[:-2])
        if resp_crc == calc_crc:
            # Extract data bytes
            byte_count = response[2]
            data = response[3:3+byte_count]
            # Convert data to list of register values
            registers = []
            for i in range(0, len(data), 2):
                reg = (data[i] << 8) + data[i+1]
                registers.append(reg)
            return registers
    return None

def write_single_register(slave_addr, reg_addr, value):
    frame = bytearray()
    frame.append(slave_addr)
    frame.append(0x06)  # Function code for Write Single Register
    frame.append((reg_addr >> 8) & 0xFF)
    frame.append(reg_addr & 0xFF)
    frame.append((value >> 8) & 0xFF)
    frame.append(value & 0xFF)
    crc = modbus_crc(frame)
    frame.append(crc & 0xFF)
    frame.append((crc >> 8) & 0xFF)
    uart.write(frame)
    time.sleep(0.05)  # Short delay
    # Read response (should be identical to the request)
    response = uart.read(8)
    if response and len(response) == 8:
        resp_crc = response[-2] + (response[-1] << 8)
        calc_crc = modbus_crc(response[:-2])
        if resp_crc == calc_crc:
            return True
    return False

def url_decode(s):
    result = ''
    i = 0
    while i < len(s):
        if s[i] == '+':
            result += ' '
            i += 1
        elif s[i] == '%':
            hex_value = s[i+1:i+3]
            result += chr(int(hex_value, 16))
            i += 3
        else:
            result += s[i]
            i += 1
    return result

# Connect to Wi-Fi
def connect_wifi(ssid, password):
    station = network.WLAN(network.STA_IF)
    station.active(True)
    station.connect(ssid, password)

    while not station.isconnected():
        print("Connecting to Wi-Fi...")
        time.sleep(1)
    print("Connected to Wi-Fi")
    print("IP Address:", station.ifconfig()[0])

connect_wifi(SSID, PASSWORD)

# Start HTTP server
def start_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(1)
    print('Listening on', addr)
    return s

server_socket = start_server()

# Mapping of mode options to values
mode_options = {
    'stop': 1,
    'run': 2,
    'reverse': 4,
    'forward': 8
}

# Reverse mapping for displaying the current mode
mode_values_to_names = {v: k for k, v in mode_options.items()}

while True:
    try:
        client_socket, addr = server_socket.accept()
        print('Client connected from', addr)
        request = client_socket.recv(1024)
        request_str = request.decode('utf-8')
        print("Request:")
        print(request_str)

        # Simple request parsing
        if 'POST' in request_str:
            # Extract the form data
            content_length = 0
            headers, body = request_str.split('\r\n\r\n', 1)
            header_lines = headers.split('\r\n')
            for line in header_lines:
                if 'Content-Length:' in line:
                    content_length = int(line.split(':')[1].strip())
            while len(body) < content_length:
                body += client_socket.recv(1024).decode('utf-8')
            print("Body:")
            print(body)
            # Parse form data
            form_data = {}
            for pair in body.split('&'):
                key_value = pair.split('=')
                key = url_decode(key_value[0])
                value = url_decode(key_value[1]) if len(key_value) > 1 else ''
                form_data[key] = value

            # Update Modbus registers based on form data
            mode_selection = form_data.get('mode_selection', 'stop')
            mode_value = mode_options.get(mode_selection, 1)
            # Write to 0x2000
            write_single_register(slave_address, 0x2000, mode_value)

            frequency = int(form_data.get('frequency', '0'))
            if 0 <= frequency <= 500:
                # Write to 0x2001
                write_single_register(slave_address, 0x2001, frequency)

        # Read Modbus registers to get current values
        registers = read_holding_registers(slave_address, 0x2000, 2)
        if registers:
            mode_value = registers[0]
            frequency = registers[1]
            mode_name = mode_values_to_names.get(mode_value, 'unknown')
        else:
            mode_value = 1
            frequency = 0
            mode_name = 'stop'

        # Build HTML response
        html_response = '''<!DOCTYPE html>
<html>
<head>
<title>Modbus Controller</title>
</head>
<body>
<h1>Modbus Controller</h1>
<form method="POST">
  Mode of Operation:
  <select name="mode_selection">
    <option value="stop" {stop_selected}>Stop</option>
    <option value="run" {run_selected}>Run</option>
    <option value="reverse" {reverse_selected}>Reverse</option>
    <option value="forward" {forward_selected}>Forward</option>
  </select><br>
  Frequency (0-500 Hz): <input type="number" name="frequency" min="0" max="500" value="{frequency}"><br>
  <input type="submit" value="Update">
</form>
</body>
</html>
'''.format(
    frequency=frequency,
    stop_selected='selected' if mode_name == 'stop' else '',
    run_selected='selected' if mode_name == 'run' else '',
    reverse_selected='selected' if mode_name == 'reverse' else '',
    forward_selected='selected' if mode_name == 'forward' else ''
)

        # Send HTTP response
        response = 'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n' + html_response
        client_socket.send(response.encode('utf-8'))
        client_socket.close()
    except Exception as e:
        print("Error:", e)
        try:
            client_socket.close()
        except:
            pass
