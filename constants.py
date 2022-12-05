https://powcoder.com
代写代考加微信 powcoder
Assignment Project Exam Help
Add WeChat powcoder
https://powcoder.com
代写代考加微信 powcoder
Assignment Project Exam Help
Add WeChat powcoder
import os
import re
import threading
import time


RECEIVE_SIZE = 128


class MessageGenerator(object):
    """
    DO NOT MODIFY!
    """
    SUCCESS = "S"
    FAILURE = "F"

    REGEX_VALID_TCP_BUFFER = re.compile(r"^(?P<payload_length>\d+):(?P<payload>.+)")
    REGEX_MSG_CONNECTION = re.compile(r"CONNECTION\|(?P<index>\d)")
    REGEX_MSG_READY = re.compile(r"READY")
    REGEX_MSG_DATA = re.compile(r"DATA\|(?P<data>.+)")
    REGEX_MSG_RESPONSE = re.compile(r"RESPONSE\|(?P<status>{}|{})".format(SUCCESS, FAILURE))

    @staticmethod
    def gen_connection(index):
        assert isinstance(index, int)
        payload = "CONNECTION|{}".format(index)
        return "{}:{}".format(len(payload), payload)

    @staticmethod
    def gen_ready():
        payload = "READY"
        return "{}:{}".format(len(payload), payload)

    @staticmethod
    def gen_data(data):
        assert isinstance(data, str)
        payload = "DATA|{}".format(data)
        return "{}:{}".format(len(payload), payload)

    @staticmethod
    def gen_response(successful):
        assert isinstance(successful, bool)
        payload = "RESPONSE|{}".format(MessageGenerator.SUCCESS if successful else MessageGenerator.FAILURE)
        return "{}:{}".format(len(payload), payload)


class Folders(object):
    TEST_FOLDER = "tests"
    OUTPUT_FOLDER = "outputs"


class OutputWriter(object):
    """
    DO NOT MODIFY!
    """
    REGEX_OPENING = re.compile(r"(?P<t>\d+\.\d*):OutputWriter opening")
    REGEX_CLOSING = re.compile(r"(?P<t>\d+\.\d*):OutputWriter closing")
    REGEX_CONNECTION_START = re.compile(r"(?P<t>\d+\.\d*):(?P<index>\d):connection:start")
    REGEX_CONNECTION_END = re.compile(r"(?P<t>\d+\.\d*):(?P<index>\d):connection:end")
    REGEX_RECEIVED = re.compile(r"(?P<t>\d+\.\d*):(?P<index>\d):(?P<status>{}|{}):(?P<data>.+)".format(MessageGenerator.SUCCESS, MessageGenerator.FAILURE))
    REGEX_BUFFER_SET = re.compile(r"(?P<t>\d+\.\d*):(?P<index>\d):buffer:(?P<size>\d+)")

    def __init__(self, output_filename):
        self.output_filename = output_filename
        self.output_file = open(self.output_filename, "w")
        self.write_lock = threading.Lock()
        self.is_closed = False
        self.start_time = time.time() * 1000
        with self.write_lock:
            self.output_file.write("{}:OutputWriter opening\n".format(self._get_ms_since_start()))

    @staticmethod
    def gen_output_filename(input_filename):
        base = os.path.splitext(os.path.basename(input_filename))
        return os.path.join(Folders.OUTPUT_FOLDER, "{}.output".format(base[0]))

    def _get_ms_since_start(self):
        return round(time.time() * 1000 - self.start_time, 2)

    def close(self):
        with self.write_lock:
            self.output_file.write("{}:OutputWriter closing\n".format(self._get_ms_since_start()))
        self.is_closed = True
        self.output_file.close()

    def is_alive(self):
        return not self.is_closed

    def write_connection_start(self, index):
        assert not self.is_closed, "OutputGenerator already closed.  Cannot write to output anymore."
        assert isinstance(index, int)
        output = "{}:{}:connection:start\n".format(self._get_ms_since_start(), index)
        with self.write_lock:
            self.output_file.write(output)

    def write_connection_end(self, index):
        assert not self.is_closed, "OutputGenerator already closed.  Cannot write to output anymore."
        assert isinstance(index, int)
        output = "{}:{}:connection:end\n".format(self._get_ms_since_start(), index)
        with self.write_lock:
            self.output_file.write(output)

    def write_received(self, index, message, successfully_processed):
        assert not self.is_closed, "OutputGenerator already closed.  Cannot write to output anymore."
        assert isinstance(index, int)
        assert isinstance(message, str)
        assert isinstance(successfully_processed, bool)
        status = MessageGenerator.SUCCESS if successfully_processed else MessageGenerator.FAILURE
        output = "{}:{}:{}:{}\n".format(self._get_ms_since_start(), index, status, message)
        with self.write_lock:
            self.output_file.write(output)

    def write_buffer_set(self, index, new_size):
        assert not self.is_closed, "OutputGenerator already closed.  Cannot write to output anymore."
        assert isinstance(index, int)
        assert isinstance(new_size, int)
        output = "{}:{}:buffer:{}\n".format(self._get_ms_since_start(), index, new_size)
        with self.write_lock:
            self.output_file.write(output)


class BackupWriter(object):
    """
    DO NOT MODIFY!
    """
    def __init__(self, backup_filename):
        self.backup_filename = backup_filename
        self.backup_file = open(self.backup_filename, "w")
        self.write_lock = threading.Lock()
        self.is_closed = False

    @staticmethod
    def gen_primary_filename(input_filename, index):
        base = os.path.splitext(os.path.basename(input_filename))
        return os.path.join(Folders.OUTPUT_FOLDER, "{}_primary_{}.txt".format(base[0], index))

    @staticmethod
    def gen_backup_filename(input_filename, index):
        base = os.path.splitext(os.path.basename(input_filename))
        return os.path.join(Folders.OUTPUT_FOLDER, "{}_backup_{}.txt".format(base[0], index))

    def close(self):
        self.is_closed = True
        self.backup_file.close()

    def is_alive(self):
        return not self.is_closed

    def append_to_backup_file(self, new_data):
        with self.write_lock:
            self.backup_file.write(new_data)