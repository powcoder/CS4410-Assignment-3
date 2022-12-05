https://powcoder.com
代写代考加微信 powcoder
Assignment Project Exam Help
Add WeChat powcoder
https://powcoder.com
代写代考加微信 powcoder
Assignment Project Exam Help
Add WeChat powcoder
import argparse
import filecmp
import os
import re
import signal
import subprocess
import threading
import time
from collections import OrderedDict

from constants import MessageGenerator, Folders, OutputWriter, BackupWriter
from master import Master


class Node(object):
    SERVER_START = 0
    SERVER_STOP = 1
    CLIENT_START = 2
    CLIENT_STOP = 3
    SEND = 4
    WAIT = 5


    def __init__(self, index, operation, value=None, dependencies=None):
        assert 0 <= operation <= 5
        assert dependencies is None or isinstance(dependencies, list)

        self.index = index
        self.operation = operation
        self.value = value              # seconds if WAIT, remaining num_characters for SEND
        self.dependencies = dependencies if dependencies is not None else []
        self.time_start = -1
        self.time_end = -1

    def set_time_start(self, time):
        if self.operation == Node.CLIENT_START or self.operation == Node.SERVER_START:
            self.time_start = time
            self.time_end = time + 500      # milliseconds
        elif self.operation == Node.WAIT:
            self.time_start = time
            self.time_end = time + self.value * 1000        # milliseconds
        elif self.operation == Node.SEND:
            # This is special; if the start time has been set, then this means that this send isn't the first send, so
            # we actually want to set the end time not the start time
            if self.time_start < 0:
                self.time_start = time
                self.time_end = time
            else:
                self.time_end = time
        else:
            self.time_start = time
            self.time_end = time

    def finished_all_dependencies(self):
        if len(self.dependencies) == 0:
            return True

        # This is needed to verify that everything was sent before the client was stopped
        finished_sending_everything = True
        if self.operation == Node.CLIENT_STOP:
            sending_dependencies = list(filter(lambda x: x.operation == Node.SEND, self.dependencies))
            if len(sending_dependencies) > 0:
                finished_sending_everything = (sending_dependencies[0].value == 0)

        # This checks that everything that was supposed to happen before this operation happened
        everything_has_time_end = all([dependency.time_end >= 0 for dependency in self.dependencies])

        return finished_sending_everything and everything_has_time_end

    def get_expected_time(self):
        max_time_end_of_dependencies = 0
        assert self.finished_all_dependencies(), "Didn't complete all dependencies!!!"
        for dependency in self.dependencies:
            max_time_end_of_dependencies = max(max_time_end_of_dependencies, dependency.time_end)
        return max_time_end_of_dependencies


class ExecGraph(object):
    SERVER_INDEX = -1

    def __init__(self):
        self.graph = {ExecGraph.SERVER_INDEX: []}
        self.clients = []
        self.client_send_amounts = {}

        # Keeps track of where we are in the execution graph
        self.graph_current_node_indices = None

        # Buffer sizes (duplicated because 1 gets modified)
        self.buffer_sizes_1 = {}
        self.buffer_sizes_2 = {}

    def add_new_node(self, line):
        """
        :param line: Line in input file
        :return: True is successful, False otherwise
        """
        match = re.match(Master.VALID_INPUTS["start_server"], line)
        if match:
            node = Node(ExecGraph.SERVER_INDEX, Node.SERVER_START)
            self.graph[ExecGraph.SERVER_INDEX].append(node)
            return True

        match = re.match(Master.VALID_INPUTS["stop_server"], line)
        if match:
            dependencies = [self.graph[ExecGraph.SERVER_INDEX][-1]]
            node = Node(ExecGraph.SERVER_INDEX, Node.SERVER_STOP, dependencies=dependencies)
            self.graph[ExecGraph.SERVER_INDEX].append(node)
            return True

        match = re.match(Master.VALID_INPUTS["start_client"], line)
        if match:
            index = int(match.group("index"))
            dependencies = [self.graph[ExecGraph.SERVER_INDEX][-1]]
            node = Node(ExecGraph.SERVER_INDEX, Node.CLIENT_START, dependencies=dependencies)
            self.graph[ExecGraph.SERVER_INDEX].append(node)
            self.clients.append(index)
            return True

        match = re.match(Master.VALID_INPUTS["stop_client"], line)
        if match:
            index = int(match.group("index"))
            dependencies = [self.graph[ExecGraph.SERVER_INDEX][-1]]
            if index in self.client_send_amounts:
                dependencies.append(self.graph[index][-1])
            node = Node(index, Node.CLIENT_STOP, dependencies=dependencies)
            self.graph[ExecGraph.SERVER_INDEX].append(node)
            return True

        match = re.match(Master.VALID_INPUTS["set_buffer"], line)
        if match:
            index = int(match.group("index"))
            size = int(match.group("size"))
            num_recvs = int(match.group("num_recvs"))
            if index not in self.buffer_sizes_1:
                self.buffer_sizes_1[index] = [[0, 0]]
                self.buffer_sizes_2[index] = [[0, 0]]
            self.buffer_sizes_1[index].append([size, num_recvs])
            self.buffer_sizes_2[index].append([size, num_recvs])
            return True

        match = re.match(Master.VALID_INPUTS["client_msg"], line)
        if match:
            index = int(match.group("index"))
            num_characters = int(match.group("num_characters"))
            dependencies = [self.graph[ExecGraph.SERVER_INDEX][-1]]
            node = Node(index, Node.SEND, value=num_characters, dependencies=dependencies)
            if index not in self.graph:
                self.graph[index] = [node]
            self.client_send_amounts[index] = num_characters
            return True

        match = re.match(Master.VALID_INPUTS["wait"], line)
        if match:
            seconds = float(match.group("seconds"))
            dependencies = [self.graph[ExecGraph.SERVER_INDEX][-1]]
            node = Node(ExecGraph.SERVER_INDEX, Node.WAIT, value=seconds, dependencies=dependencies)
            self.graph[ExecGraph.SERVER_INDEX].append(node)
            return True

        return False

    def initialize_execution_indices(self):
        self.graph_current_node_indices = {index: -1 for index in self.graph.keys()}
        self.next_node(ExecGraph.SERVER_INDEX, 0)

    def prev_node(self, index):
        if self.graph_current_node_indices[index] - 1 < 0:
            return None
        return self.graph[index][self.graph_current_node_indices[index] - 1]

    def curr_node(self, index):
        if self.graph_current_node_indices[index] < 0 or self.graph_current_node_indices[index] >= len(self.graph[index]):
            return None

        assert not self.finished_execution_for_index(index), "Can't get node because finished exec for {}".format(index)
        return self.graph[index][self.graph_current_node_indices[index]]

    def next_node(self, index, t):
        if index not in self.graph:
            return

        self.graph_current_node_indices[index] += 1
        if self.graph_current_node_indices[index] > 0:
            # There was a node before this
            prev_node = self.prev_node(index)
            prev_node.set_time_start(t)

            curr_node = self.curr_node(index)
            if curr_node is not None and index == ExecGraph.SERVER_INDEX and curr_node.operation == Node.WAIT:
                self.next_node(index, prev_node.time_end)

    def finished_execution_for_index(self, index=None):
        """
        :param index: If None, then check for all keys
        :return: True if for the given index, all expected executions have completed; False otherwise
        """
        if index is None:
            indices = self.graph.keys()
        else:
            indices = [index]

        return all([self.graph_current_node_indices[index] >= len(self.graph[index]) for index in indices])


class Grading(object):
    TIMEOUT = 15            # seconds
    TIMING_THRESHOLD = 1000    # milliseconds

    PASS = 0
    FAIL_COUNT = 1
    FAIL_SPEC = 2
    FAIL_EXCEPTION = 3

    def __init__(self, is_phase_1):
        self.is_phase_1 = is_phase_1

        # Used when running tests
        self.completed = dict()
        self.completed_lock = threading.Lock()

    def grade_all(self):
        # Results of tests
        tests_status = OrderedDict()
        tests_reason = OrderedDict()

        tests = []
        for file in os.listdir("tests"):
            if file.endswith(".input"):
                tests.append(file)

        for input in sorted(tests):
            input_filepath = os.path.join("tests", input)

            with self.completed_lock:
                self.completed[input] = False

            process = subprocess.Popen(["python3", "master.py", input_filepath])
            threading.Thread(target=self.timeout, args=[process.pid, input]).start()
            _ = process.communicate()
            with self.completed_lock:
                self.completed[input] = True
            rc = process.returncode
            if rc != 0:
                tests_status[input], tests_reason[input] = self.FAIL_EXCEPTION, "master failed to terminate"
                continue

            # Check the output file
            time.sleep(0.5)
            output_filepath = OutputWriter.gen_output_filename(input_filepath)
            if not os.path.exists(output_filepath):
                tests_status[input], tests_reason[input] = self.FAIL_EXCEPTION, "{} doesn't exist".format(output_filepath)

            try:
                tests_status[input], tests_reason[input] = self.check_output_with_input(input_filepath, output_filepath)
            except Exception as e:
                tests_status[input], tests_reason[input] = self.FAIL_EXCEPTION, "grading script couldn't run on output"
                continue

        with open("results.txt", "w") as results:
            for test in tests_status.keys():
                print("{}: {}\t\t{}".format(tests_status[test], test, tests_reason[test]))
                results.write("{}: {}\t\t{}\n".format(tests_status[test], test, tests_reason[test]))

    def timeout(self, pid, input):
        timeout = Grading.TIMEOUT
        while timeout > 0:
            with self.completed_lock:
                if self.completed[input]:
                    return
            time.sleep(min(1, timeout))
            timeout -= 1
        with self.completed_lock:
            if not self.completed[input]:
                try:
                    os.kill(pid, signal.SIGKILL)
                except:
                    raise Exception("Tried to kill pid {}, but already dead (perhaps caused by an exception in your code)".format(pid))

    def check_output_with_input(self, input_filepath, output_filepath):
        graph = ExecGraph()
        with open(input_filepath) as input:
            for line in input:
                line = line.strip()
                if not line:
                    continue

                success = graph.add_new_node(line)
                if not success:
                    return self.FAIL_EXCEPTION, "Invalid line in inputs: '{}'".format(line)

        num_messages = {}           # Keeps track of the number of success and failure messages
        graph.initialize_execution_indices()
        with open(output_filepath) as output:
            for line in output:
                line = line.rstrip("\n")
                if not line:
                    continue

                if graph.finished_execution_for_index(ExecGraph.SERVER_INDEX):
                    return self.FAIL_SPEC, "No more lines expected, but got '{}'".format(line)

                match = re.match(OutputWriter.REGEX_OPENING, line)
                if match:
                    t = float(match.group("t"))

                    # Check to make sure that this is what was expected
                    current_operation = graph.curr_node(ExecGraph.SERVER_INDEX)
                    if current_operation.operation != Node.SERVER_START:
                        return self.FAIL_SPEC, "Expected server start, but got '{}'".format(line)
                    if not current_operation.finished_all_dependencies():
                        return self.FAIL_SPEC, "Didn't finish all dependencies before '{}'".format(line)

                    # Check expected time
                    expected_time = current_operation.get_expected_time()
                    if not self.within_expected_time_range(expected_time, t):
                        return self.FAIL_SPEC, "server starting time should be {}, but got {}".format(expected_time, t)

                    # Update node information and move on to next node
                    graph.next_node(ExecGraph.SERVER_INDEX, t)

                    continue

                match = re.match(OutputWriter.REGEX_CLOSING, line)
                if match:
                    t = float(match.group("t"))

                    # Check to make sure that this is what was expected
                    current_operation = graph.curr_node(ExecGraph.SERVER_INDEX)
                    if current_operation.operation != Node.SERVER_STOP:
                        return self.FAIL_SPEC, "Expected server stop, but got '{}'".format(line)

                    # Check expected time
                    expected_time = current_operation.get_expected_time()
                    if not self.within_expected_time_range(expected_time, t):
                        return self.FAIL_SPEC, "server stopping time should be {}, but got {}".format(expected_time, t)
                    if not current_operation.finished_all_dependencies():
                        return self.FAIL_SPEC, "Didn't finish all dependencies before '{}'".format(line)

                    # Update node information and move on to next node
                    graph.next_node(ExecGraph.SERVER_INDEX, t)

                    continue

                match = re.match(OutputWriter.REGEX_CONNECTION_START, line)
                if match:
                    t = float(match.group("t"))
                    index = int(match.group("index"))

                    # Check to make sure that this is what was expected
                    current_operation = graph.curr_node(ExecGraph.SERVER_INDEX)
                    if current_operation.operation != Node.CLIENT_START:
                        return self.FAIL_SPEC, "Expected client start, but got '{}'".format(line)
                    if not current_operation.finished_all_dependencies():
                        return self.FAIL_SPEC, "Didn't finish all dependencies before '{}'".format(line)

                    # Check expected time
                    expected_time = current_operation.get_expected_time()
                    if not self.within_expected_time_range(expected_time, t):
                        return self.FAIL_SPEC, "client starting time should be {}, but got {}".format(expected_time, t)

                    # Update node information and move on to next node
                    graph.next_node(ExecGraph.SERVER_INDEX, t)
                    graph.next_node(index, t)

                    continue

                match = re.match(OutputWriter.REGEX_CONNECTION_END, line)
                if match:
                    t = float(match.group("t"))
                    index = int(match.group("index"))

                    # Check to make sure that this is what was expected
                    current_operation = graph.curr_node(ExecGraph.SERVER_INDEX)
                    if current_operation.operation != Node.CLIENT_STOP:
                        return self.FAIL_SPEC, "Expected client start, but got '{}'".format(line)
                    if not current_operation.finished_all_dependencies():
                        return self.FAIL_SPEC, "Didn't finish all dependencies before '{}'".format(line)

                    # Check expected time
                    expected_time = current_operation.get_expected_time()
                    if not self.within_expected_time_range(expected_time, t):
                        return self.FAIL_SPEC, "client starting time should be {}, but got {}".format(expected_time, t)

                    # Update node information and move on to next node
                    graph.next_node(ExecGraph.SERVER_INDEX, t)

                    continue

                match = re.match(OutputWriter.REGEX_BUFFER_SET, line)
                if match:
                    t = float(match.group("t"))
                    index = int(match.group("index"))
                    size = int(match.group("size"))

                    # Check to make sure that buffer size was set correctly
                    if index not in graph.buffer_sizes_1 or len(graph.buffer_sizes_1[index]) == 0 or graph.buffer_sizes_1[index][0][1] != 0:
                        return self.FAIL_SPEC, "Didn't set buffer size for {} correctly".format(index)
                    graph.buffer_sizes_1[index].pop(0)
                    if graph.buffer_sizes_1[index][0][0] != size:
                        return self.FAIL_SPEC, "Buffer size for {} set to {} but expected {}".format(index, graph.buffer_sizes_1[index][0][0], size)

                    continue

                match = re.match(OutputWriter.REGEX_RECEIVED, line)
                if match:
                    t = float(match.group("t"))
                    index = int(match.group("index"))
                    status = match.group("status") if not self.is_phase_1 else MessageGenerator.SUCCESS
                    data = match.group("data")

                    # Check to make sure client was supposed to send a message in the first place
                    if index not in graph.graph.keys():
                        return self.FAIL_SPEC, "Client {} wasn't supposed to send a message!".format(index)

                    # Check to make sure that this is what was expected
                    current_operation = graph.curr_node(index)
                    if current_operation.operation != Node.SEND:
                        return self.FAIL_SPEC, "Expected send, but got '{}'".format(line)
                    if not current_operation.finished_all_dependencies():
                        return self.FAIL_SPEC, "Didn't finish all dependencies before '{}'".format(line)

                    # Check expected time (only for first send operation)
                    if current_operation.time_end < 0:
                        expected_time = current_operation.get_expected_time()
                        if not self.within_expected_time_range(expected_time, t):
                            return self.FAIL_SPEC, "send time should be {}, but got {}".format(expected_time, t)

                    # Update node information and move on to next node (if needed)
                    current_operation.set_time_start(t)
                    if status == MessageGenerator.SUCCESS:
                        current_operation.value -= len(data)
                        if current_operation.value == 0:
                            graph.next_node(index, t)

                    # If Phase 2/3, then check to make sure that the buffer size rules are followed
                    if not self.is_phase_1:
                        if index not in graph.buffer_sizes_1 or len(graph.buffer_sizes_1[index]) == 0 or graph.buffer_sizes_1[index][0][1] == 0:
                            return self.FAIL_SPEC, "No buffer size for {}".format(index)
                        if status == MessageGenerator.SUCCESS and len(data) > graph.buffer_sizes_1[index][0][0]:
                            return self.FAIL_SPEC, "Wrong status for {}".format(index)
                        graph.buffer_sizes_1[index][0][1] = max(-1, graph.buffer_sizes_1[index][0][1] - 1)

                    # Record down number of success/failure messages
                    if index not in num_messages:
                        num_messages[index] = {MessageGenerator.SUCCESS: 0, MessageGenerator.FAILURE: 0}
                    num_messages[index][status] += 1

                    continue

                # This is an invalid statement to have
                return self.FAIL_SPEC, "Invalid line in output '{}'".format(line)

        # Make sure everything that needed to be done are done
        if not graph.finished_execution_for_index():
            return self.FAIL_SPEC, "Missing lines in output!"

        # Check to make sure the backup matches primary
        for index in graph.client_send_amounts.keys():
            primary_filepath = BackupWriter.gen_primary_filename(input_filepath, index)
            backup_filepath = BackupWriter.gen_backup_filename(input_filepath, index)

            if not os.path.exists(primary_filepath):
                return self.FAIL_EXCEPTION, "{} doesn't exist".format(primary_filepath)
            if not os.path.exists(backup_filepath):
                return self.FAIL_EXCEPTION, "{} doesn't exist".format(backup_filepath)

            if not filecmp.cmp(primary_filepath, backup_filepath):
                return self.FAIL_SPEC, "Backup file differed from primary file for {}".format(index)

        # Make sure that the expected number of messages is correct
        for index, num_characters in graph.client_send_amounts.items():
            expected_num_messages_success, expected_num_messages_failure = self.calculate_expected_number_of_messages(num_characters, graph.buffer_sizes_2, index)
            if expected_num_messages_success == -1:
                return self.FAIL_SPEC, "Unable to calculate expected number of messages"
            if expected_num_messages_success != num_messages[index][MessageGenerator.SUCCESS]:
                return self.FAIL_COUNT, "Expected {} success messages, but got {} success messages".format(expected_num_messages_success, num_messages[index][MessageGenerator.SUCCESS])
            if expected_num_messages_failure != num_messages[index][MessageGenerator.FAILURE]:
                return self.FAIL_COUNT, "Expected {} failure messages, but got {} failure messages".format(expected_num_messages_failure, num_messages[index][MessageGenerator.FAILURE])

        return self.PASS, "Passed!"

    def get_expected_time(self, operations, prev_operation):
        if len(operations) > 0 and operations[0][0] == 4:
            wait_op = operations.pop(0)
            expected_time = prev_operation[2] + wait_op[1]
        else:
            expected_time = 0

        return expected_time

    def within_expected_time_range(self, actual_time, expected_time):
        if expected_time <= 0:
            return True
        else:
            return abs(actual_time - expected_time) < Grading.TIMING_THRESHOLD

    def calculate_expected_number_of_messages(self, num_characters, buffer_sizes, index):
        if self.is_phase_1:
            return 1, 0

        buffer_size = buffer_sizes[index]
        if not buffer_size:
            return -1, -1

        args = ["tests/message_count.out", str(num_characters)]
        for line in buffer_size:
            args.extend(list(map(str, line)))
        process = subprocess.Popen(args, stdout=subprocess.PIPE)
        num_messages_success = -1
        num_messages_failure = -1
        p_std_out = process.communicate()[0]
        if process.returncode == 0:
            num_messages_success, num_messages_failure = map(int,p_std_out.strip().split())

        return num_messages_success, num_messages_failure


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1", "-p1", action="store_true", help="Is this for Phase 1 of the project?")
    args = parser.parse_args()
    Grading(args.phase1).grade_all()
