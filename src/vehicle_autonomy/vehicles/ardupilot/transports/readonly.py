"""Serial receive capability without any exposed write method."""


class ReadOnlySerial:
    def __init__(self, path, baudrate):
        import serial
        self._connection = serial.Serial(path, baudrate, timeout=0, exclusive=True)

    def read(self, count):
        return self._connection.read(count)

    def close(self):
        self._connection.close()
