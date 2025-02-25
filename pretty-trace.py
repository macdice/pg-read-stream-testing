import re
import shutil
import sys

BLCKSZ                = 8192
#COLUMNS, LINES        = shutil.get_terminal_size()
COLUMNS               = 78 # diagrams that don't wrap in email?

# sequential read brackets
SEQUENCE_READ         = "─"
SEQUENCE_FIRST        = "╮"
SEQUENCE_STRETCH      = "│"
SEQUENCE_MORE         = "┤"
SEQUENCE_LAST         = "╯"
SEQUENCE_ISOLATED     = "╴"

# connections between fadvise and read
CONNECTION_TEXT       = 64 # non-graph text the connection must fit between
CONNECTION_WIDTH      = COLUMNS - CONNECTION_TEXT
CONNECTION_MARGIN     = 2
CONNECTION_EMPTY      = " "
CONNECTION_HORIZONTAL = "─"
CONNECTION_START      = "●"
CONNECTION_TURN1      = "╮"
CONNECTION_VERTICAL   = "│"
CONNECTION_CROSS      = "┼"
CONNECTION_TURN2      = "╰"
CONNECTION_END        = "►"

#  Linux: strace assuming eg -s100 for strings, -t for elapsed time
#  FreeBSD: TODO: need truss -d elapsed time format
#  macOS: TODO: need dtruss format and fcntl instead of fadvise
RE_PARAMETERS         = r"=== effective_io_concurrency ([0-9]+), range size ([0-9]+) ==="
RE_LSEEK              = r"lseek[0-9]+\(([0-9]+),"
RE_FADVISE            = r"fadvise[0-9]+\(([0-9]+), ?([0-9]+), ?([0-9]+),.*<([0-9.]+)>"
RE_PREAD              = r"(preadv?)[0-9]+\(([0-9]+),.*, ?([0-9]+)\) *= *([0-9]+).*<([0-9.]+)>"

# output format
FORMAT_FADVISE        = "{syscall:<6} {blocks::>2} {first:>3}..{last:<3} {time} {connection_plot}                             {sequence_plot}"
FORMAT_PREAD          = "                             {connection_plot} {syscall:<6} {blocks:>2} {first:>3}..{last:<3} {time} {sequence_plot}"

# sanity check
if CONNECTION_WIDTH < (CONNECTION_MARGIN * 2 + 1):
        raise Error("terminal too narrow to plot even one connection")

def find_free_position(connections):
        # To minimise overlapping, choose the position to the left of
        # the current left-most connection.
        left_most = None
        for i in range(len(connections) - CONNECTION_MARGIN, CONNECTION_MARGIN, -1):
                if connections[i] != CONNECTION_EMPTY:
                        left_most = i
        if left_most and left_most - 1 > CONNECTION_MARGIN:
                return left_most - 1

        # If there was no space left there, then search for a free
        # column from the right.
        for i in range(len(connections) - CONNECTION_MARGIN - 1, CONNECTION_MARGIN, -1):
                if connections[i] == CONNECTION_EMPTY:
                        return i

        raise Error("terminal too narrow to plot required number of connections")

def connections_to_string(connections):
        return "".join(connections)

def plot_fadvise(connections, position):
        # Update "connections" to add our second line segment.
        connections[position] = CONNECTION_VERTICAL
        # Return a string showing the first line segment.
        this_connections = connections.copy()
        for i in range(position):
                if this_connections[i] == CONNECTION_VERTICAL:
                        this_connections[i] = CONNECTION_CROSS
                else:
                        this_connections[i] = CONNECTION_HORIZONTAL
        this_connections[0] = CONNECTION_START
        this_connections[position] = CONNECTION_TURN1
        return connections_to_string(this_connections)

def plot_pread(connections, position):
        # Update "connections" to remove our second line segment.
        connections[position] = CONNECTION_EMPTY
        # Return a string showing the third line segment.
        this_connections = connections.copy()
        for i in range(position, len(connections)):
                if this_connections[i] == CONNECTION_VERTICAL:
                        this_connections[i] = CONNECTION_CROSS
                else:
                        this_connections[i] = CONNECTION_HORIZONTAL
        this_connections[position] = CONNECTION_TURN2
        this_connections[-1] = CONNECTION_END
        return connections_to_string(this_connections)

def dump(syscalls):
        connections = [CONNECTION_EMPTY] * (CONNECTION_WIDTH + CONNECTION_MARGIN * 2)
        connection_positions = {}
        last_read_seq = False
        for i in range(len(syscalls)):
                syscall, offset, size, time = syscalls[i]
                first = int(offset / BLCKSZ)
                last = int(((offset + size) / BLCKSZ) - 1)
                blocks = last - first + 1

                # Plot the fadvise->pread connections.
                if syscall == "fadvise":
                        position = find_free_position(connections)
                        connection_plot = plot_fadvise(connections, position)
                        connection_positions[offset] = position
                else:
                        if offset not in connection_positions:
                                connection_plot = connections_to_string(connections)
                        else:
                                connection_plot = plot_pread(connections, connection_positions[offset])

                # Plot the sequential read bracket.  This requires
                # looking ahead to find the end, which is why we read
                # into an array first...
                if syscall.startswith("pread"):
                        # For each pread[v] call, figure out if it is
                        # sequential with the previous and next call
                        # and figure out how to plot the graph.  We
                        # have to search ahead for the next pread[v].
                        next_read_seq = False
                        for j in range(i + 1, len(syscalls)):
                                if syscalls[j][0].startswith("pread"):
                                        if syscalls[j][1] == offset + size:
                                                next_read_seq = True
                                        break
                        if next_read_seq:
                                if last_read_seq:
                                        sequence_plot = SEQUENCE_READ + SEQUENCE_MORE
                                else:
                                        sequence_plot = SEQUENCE_READ + SEQUENCE_FIRST
                        else:
                                if last_read_seq:
                                        sequence_plot = SEQUENCE_READ + SEQUENCE_LAST
                                else:
                                        sequence_plot = SEQUENCE_READ + SEQUENCE_ISOLATED
                        last_read_seq = next_read_seq
                else:
                        # For non-pread calls we just have to stretch
                        # the bracket.
                        if last_read_seq:
                                sequence_plot = " " + SEQUENCE_STRETCH
                        else:
                                sequence_plot = "  "

                if syscall == "fadvise":
                        f = FORMAT_FADVISE
                else:
                        f = FORMAT_PREAD
                print(f.format(syscall=syscall, blocks=blocks, first=first, last=last, time=time, connection_plot=connection_plot, sequence_plot=sequence_plot))

# Parse stdin, expecting one or more test runs, each starting with a message
# that matches our parameter pattern.  That is, the SQL should log it, and
# strace/truss should be set to show long enough strings etc -s100.
fd = None
syscalls = []
for line in sys.stdin:
        line = line.strip()
        groups = re.search(RE_PARAMETERS, line)
        if groups:
                eic = int(groups.group(1))
                size = int(groups.group(2))
                fd = None
                if len(syscalls) > 0:
                        dump(syscalls)
                syscalls = []
                print("effective_io_concurrency = %s, range size = %s" % (eic, size))
                print()
                continue
        # guess that the first lseek we see is the right file descriptor?!
        groups = re.search(RE_LSEEK, line)
        if groups:
                fd = int(groups.group(1))
                continue
        groups = re.search(RE_FADVISE, line)
        if groups:
                this_fd = int(groups.group(1))
                if this_fd != fd:
                        continue
                offset = int(groups.group(2))
                size = int(groups.group(3))
                time = groups.group(4)
                syscalls.append(("fadvise", offset, size, time))
                continue
        groups = re.search(RE_PREAD, line)
        if groups:
                syscall = groups.group(1) # might be pread or preadv
                fd = int(groups.group(2))
                if this_fd != fd:
                        continue
                offset = int(groups.group(3))
                size = int(groups.group(4))
                time = groups.group(5)
                syscalls.append((syscall, offset, size, time))
                continue
if len(syscalls) > 0:
        dump(syscalls)
