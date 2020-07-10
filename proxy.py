import argparse
import socket
import os
import hexdump
import time
import json
import parser as parser
from threading import Thread, Lock
from vectors import movetowards, dist
from util import encrypt_data, decrypt_data

DEFAULT_BIND_IP = '192.168.182.133'
DEFAULT_SERVER = 'maze.liveoverflow.com'  # 147.75.85.99

SERVER_QUEUE_RAW = []
SQR_LOCK = Lock()
CLIENT_QUEUE_RAW = []
CQR_LOCK = Lock()

CLIENT_SECRET = None
BLOCK_POSITION = False
BLOCK_POSITION_OUT = False
VERBOSITY = 1


def update_client_secret(data):
    global CLIENT_SECRET

    # just to avoid this op unnecessarily
    if CLIENT_SECRET is not None:
        return

    if data[2] in ['L', 'P']:
        CLIENT_SECRET = data[3:11]


class Proxy2Server(Thread):

    def __init__(self, host, port):
        super(Proxy2Server, self).__init__()
        self.game = None  # game client socket not known yet
        self.port = port
        self.host = host
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.settimeout(0.0001)

    # run in thread
    def run(self):
        global BLOCK_POSITION
        global VERBOSITY

        while True:
            # pop injected packets
            with CQR_LOCK:
                while len(CLIENT_QUEUE_RAW) > 0:
                    pkt = CLIENT_QUEUE_RAW.pop(0)
                    self.game.forward(pkt)

            try:
                data, addr = self.server.recvfrom(4096)
            except socket.timeout:
                continue

            if data:
                data_pt = decrypt_data(data)

                if VERBOSITY > 0:
                    print "[{}] <- {}".format(self.port, data_pt[:100].encode('hex'))
                    hexdump.hexdump(data_pt)

                if BLOCK_POSITION and data_pt[2] in ['X', 'T']:
                    print 'Block teleport/logout'
                    continue
                elif data_pt[2] == 'X':
                    print 'Blocked logout'
                    continue
                elif data_pt[2] == 'Y':
                    print 'Blocked freeze'
                    continue
                #elif data_pt[2] in ['E', 'I', 'P']:
                #    # Pass through for latency
                #    self.game.forward(data)
                #    continue

                try:
                    parser.parse(data_pt[2:], self.port, 'server')
                    while len(parser.CLIENT_QUEUE) > 0:
                        pkt = parser.CLIENT_QUEUE.pop()
                        #print "got queue client: {}".format(pkt.encode('hex'))
                        self.game.forward(encrypt_data(pkt))
                except Exception as e:
                    print 'server[{}]'.format(self.port), e

    def forward(self, data):
        try:
            n_sent = 0
            while n_sent < len(data):
                n_sent += self.server.sendto(data[n_sent:], (self.host, self.port))
        except socket.timeout:
            print 'server send timeout'


class Game2Proxy(Thread):

    def __init__(self, host, port):
        super(Game2Proxy, self).__init__()
        self.server = None  # real server socket not known yet
        self.port = port
        self.host = host
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(0.0001)
        self.game = sock
        self.reply_addr = None

    def run(self):
        global BLOCK_POSITION_OUT
        global VERBOSITY

        while True:
            # pop even if nothing received from proxy (injected packets)
            with SQR_LOCK:
                while len(SERVER_QUEUE_RAW) > 0:
                    pkt = SERVER_QUEUE_RAW.pop(0)
                    self.server.forward(pkt)

            try:
                data, self.reply_addr = self.game.recvfrom(4096)
            except socket.timeout:
                continue

            if data:
                data = decrypt_data(data)

                if BLOCK_POSITION_OUT and data[2] in ['P']:
                    #print 'block c->s position'
                    continue

                if VERBOSITY > 0:
                    print "[{}] -> {}".format(self.port, data.encode('hex'))
                    hexdump.hexdump(data)

                update_client_secret(data)

                try:
                    parser.parse(data[2:], self.port, 'client')
                    if len(parser.SERVER_QUEUE) > 0:
                        pkt = parser.SERVER_QUEUE.pop()
                        #print "got queue server: {}".format(pkt.encode('hex'))
                        self.server.forward(encrypt_data(pkt))
                except Exception as e:
                    print 'client[{}]'.format(self.port), e

    def forward(self, data):
        try:
            n_sent = 0
            while n_sent < len(data):
                n_sent += self.game.sendto(data[n_sent:], self.reply_addr)
        except socket.timeout:
            print 'game send timeout'


class Proxy(Thread):

    def __init__(self, from_host, to_host, port):
        super(Proxy, self).__init__()
        self.from_host = from_host
        self.to_host = to_host
        self.port = port
        self.running = False

    def run(self):
        print "[proxy({})] setting up".format(self.port)
        self.g2p = Game2Proxy(self.from_host, self.port)  # waiting for a client
        self.p2s = Proxy2Server(self.to_host, self.port)
        print "[proxy({})] connection established".format(self.port)
        self.g2p.server = self.p2s
        self.p2s.game = self.g2p
        self.running = True

        self.g2p.start()
        self.p2s.start()


class ReplayThread(Thread):

    def __init__(self, coords,
                 send_client=True,
                 send_server=False,
                 dist_time=None,
                 rate_limit=0.2):
        super(ReplayThread, self).__init__()
        self.coords = coords
        self.send_client = send_client
        self.send_server = send_server
        self.rate_limit = rate_limit
        self.dist_time = dist_time

    def run(self):
        global BLOCK_POSITION_OUT

        if self.dist_time is not None:
            parser.FREEZE_TIME = True

        if self.send_server:
            BLOCK_POSITION_OUT = True

        discrete_replay(
            self.coords,
            send_client=self.send_client,
            send_server=self.send_server,
            dist_time=self.dist_time,
            rate_limit=self.rate_limit)

        if self.send_server:
            BLOCK_POSITION_OUT = False

        if self.dist_time is not None:
            parser.FREEZE_TIME = False
        print 'dr thread done'


class TriggerFuzzThread(Thread):

    def __init__(self, rate_limit=0.2):
        super(TriggerFuzzThread, self).__init__()
        self.rate_limit = rate_limit

    def run(self):
        trigger_fuzz(self.rate_limit)


def add_server_queue(packet):
    with SQR_LOCK:
        SERVER_QUEUE_RAW.append(packet)


def add_client_queue(packet):
    with CQR_LOCK:
        CLIENT_QUEUE_RAW.append(packet)


def smooth_coords(cur_pos, next_pos,
                  ups=5.0,
                  rate_limit=0.2):
    dist_limit = rate_limit * ups

    coords = [cur_pos]

    while dist(cur_pos, next_pos) > 0:
        cur_pos = tuple(movetowards(cur_pos, next_pos, dist_limit))
        coords.append(cur_pos)

    return coords


def smooth_teleport(cur_pos, next_pos,
                    send_client=True,
                    send_server=False,
                    speed_boost=1.0,
                    rate_limit=0.2):
    smooth_replay([cur_pos, next_pos],
                  send_client=send_client,
                  send_server=send_server,
                  speed_boost=speed_boost,
                  rate_limit=rate_limit)


def smooth_replay(coords,
                  speed_boost=1,
                  send_client=True,
                  send_server=False,
                  rate_limit=0.2):
    full_coords = []

    if rate_limit == 0.0:
        smooth_rate = 0.0001
    else:
        smooth_rate = rate_limit

    for i in range(len(coords) - 1):
        full_coords.extend(
            smooth_coords(
                coords[i], coords[i+1],
                ups=5.0 * speed_boost,
                rate_limit=smooth_rate)[:-1])

    discrete_replay(
        full_coords,
        send_client=send_client,
        send_server=send_server,
        rate_limit=rate_limit)


def discrete_replay(coords,
                    skip=0,
                    send_client=True,
                    send_server=False,
                    dist_time=None,
                    rate_limit=0.2):
    print '# coords:', len(coords)

    if dist_time is not None:
        # Scaling up time for target units per second
        # Get current game time and track how much we artificially increase it
        start_time = parser.predict_client_time()
        accrued_time = 0.0
        print 'start time:', start_time

    for i, (x, y, z) in enumerate(coords):
        print i, x, y, z
        # Only play every nth coordinate
        if skip > 1 and i % skip != 0:
            continue

        if send_client:
            telpkt = parser.teleport_packet(x, y, z)
            add_client_queue(encrypt_data(telpkt))

        if send_server:
            if dist_time is not None:
                if i > 0:
                    distance = dist(coords[i-1], coords[i])
                    # decreased it a bit lower than normal 5.0 speed to avoid getting kicked
                    normal_speed = 2.0  # 5.0 units per second, lower in case of round errors
                    normal_time = distance / normal_speed
                    new_time = (dist_time / normal_speed) * normal_time
                    accrued_time += new_time
                    #accrued_time += parser.LAST_SRV_ROUNDTRIP
                    accrued_time += 0.04
                    time_ = start_time + accrued_time
                    print 'normal time: %f -> scaled time: %f' % (
                        normal_time, new_time)
                else:
                    start_time += 1.0
                    time_ = start_time

                # sync injected hearbeat time
                parser.set_client_time(time_)
            else:
                time_ = parser.predict_client_time()

            pospkt = parser.position_packet(
                CLIENT_SECRET,
                time_,
                x, y, z,
                0, 0, 0,  # euler angles
                0xff,  # trigger
                0x7fff, 0x7fff,  # ground, notground
                raw_time=False)
            add_server_queue(encrypt_data(pospkt))

        if dist_time is not None and i < len(coords) - 1:
            units_per_second = dist_time  # default 5.0
            distance = dist(coords[i], coords[i+1])
            duration = distance / units_per_second
            print '%f seconds to next checkpoint (%f units away)' % (
                duration, distance)
            if duration > 0.0:
                time.sleep(duration)
        elif rate_limit > 0.0:
            time.sleep(rate_limit)

    print 'discrete replay finished'


def spray_coords(coords):
    socks = [(socket.socket(socket.AF_INET, socket.SOCK_DGRAM), p)
             for p in range(1338, 1358)]
    for sock in socks:
        sock[0].setblocking(0)

    if len(coords) > len(socks):
        raise Exception("too many to spray")

    time_ = parser.predict_client_time()

    for i, (x, y, z) in enumerate(coords):
        pospkt = parser.position_packet(
            CLIENT_SECRET,
            time_,
            x, y, z,
            0, 0, 0,
            0,
            0, 0)
        pospkt = encrypt_data(pospkt)
        sock, port = socks[i]
        sock.sendto(pospkt, (DEFAULT_SERVER, port))


def stuffed_position(coords):
    stuffed = ''

    time_ = parser.predict_client_time()
    for x, y, z in coords:
        pospkt = parser.position_packet(
            CLIENT_SECRET,
            time_,
            x, y, z,
            0, 0, 0,
            0,
            0, 0)
        stuffed += pospkt
        time_ += 1

    stuffed = encrypt_data(stuffed)

    print 'Sending stuff pos pkt (%u bytes)' % (len(stuffed))
    add_server_queue(stuffed)


def trigger_fuzz(rate_limit=1.0):
    for trigger in range(0x100):
        time_ = parser.predict_client_time()
        x = parser.LAST_X
        y = parser.LAST_Y
        z = parser.LAST_Z
        pospkt = parser.position_packet(
            CLIENT_SECRET,
            time_,
            x, y, z,
            0, 0, 0,
            trigger,
            0, 0)

        print 'Trigger: 0x%02x' % (trigger)
        encrypted = encrypt_data(pospkt)
        add_server_queue(encrypted)
        time.sleep(1)


def main():
    global BLOCK_POSITION, BLOCK_POSITION_OUT
    global CLIENT_SECRET
    global VERBOSITY

    BLOCK_POSITION = False

    argparser = argparse.ArgumentParser()
    argparser.add_argument('--port', type=int, default=1337)
    argparser.add_argument('--bindip', type=str,
                           default=DEFAULT_BIND_IP)
    argparser.add_argument('--server', type=str,
                           default=DEFAULT_SERVER)
    args = argparser.parse_args()

    _game_server = Proxy(args.bindip, args.server, args.port)
    _game_server.start()

    while True:
        try:
            cmd = raw_input('$ ')
            if cmd[:4] == 'quit':
                os._exit(0)
            elif cmd == 'v':
                if VERBOSITY == 0:
                    VERBOSITY = 1
                else:
                    VERBOSITY = 0
            elif cmd == 'bp':
                BLOCK_POSITION = not BLOCK_POSITION
                print 'Block position:', BLOCK_POSITION
            elif cmd == 'bpo':
                BLOCK_POSITION_OUT = not BLOCK_POSITION_OUT
                print 'Block pos out:', BLOCK_POSITION_OUT
            elif cmd == 'ft':
                parser.FREEZE_TIME = not parser.FREEZE_TIME
                print 'Freeze time:', parser.FREEZE_TIME
            elif cmd[0:2] == 'S ':
                # send to server
                add_server_queue(cmd[2:].decode('hex'))
            elif cmd[0:2] == 'C ':
                # send to client
                add_client_queue(cmd[2:].decode('hex'))
            elif cmd.startswith('chat_l '):
                msg = cmd[len('chat_l'):]
                data = ' ' + msg
                print data
                add_client_queue(encrypt_data(data))
            elif cmd.startswith('chat_r '):
                msg = cmd[len('chat_r'):]
                data = ' ' + CLIENT_SECRET + msg
                add_server_queue(encrypt_data(data))
            elif cmd[0:2] == 'T ':
                x, y, z = (float(x) for x in cmd[2:].split(' '))
                telpkt = parser.teleport_packet(x, y, z, flag=1)
                add_client_queue(encrypt_data(telpkt))
            elif cmd[0:2] == 'Z ':
                x, y, z = (float(x) for x in cmd[2:].split(' '))

                #BLOCK_POSITION = True

                cur_x = parser.LAST_X
                cur_y = parser.LAST_Y
                cur_z = parser.LAST_Z

                smooth_teleport((cur_x, cur_y, cur_z),
                                (x, y, z),
                                send_server=True,
                                send_client=False,
                                rate_limit=0.1)

                #BLOCK_POSITION = False
            elif cmd == 'startrec' and not parser.RECORD_PLAYER_POS:
                print 'started recording'
                parser.RECORD_PLAYER_POS = True

                if parser.PLAYER_POS_HIST is not None:
                    parser.PLAYER_POS_HIST = None
            elif cmd == 'stoprec' and parser.RECORD_PLAYER_POS:
                print 'stopped recording'
                parser.RECORD_PLAYER_POS = False
                print 'Recorded %u positions' % (len(parser.PLAYER_POS_HIST))
            elif cmd.startswith('playrec'):
                if parser.PLAYER_POS_HIST is not None:
                    coords = parser.PLAYER_POS_HIST[:]
                    cmd = cmd.split(' ')

                    rate = 0.14
                    if len(cmd) > 1:
                        try:
                            rate = float(cmd[-1])
                        except ValueError:
                            pass

                    if 'rev' in cmd:
                        coords = coords[::-1]
                    if 'stuf' in cmd:
                        stuffed_position(coords)
                    elif 'spray' in cmd:
                        spray_coords(coords)
                    elif 'speed' in cmd:
                        last_pos = (parser.LAST_X, parser.LAST_Y, parser.LAST_Z)
                        if None not in last_pos:
                            print 'injecting last position:', last_pos
                            coords.insert(0, last_pos)

                        dr = ReplayThread(
                            coords,
                            send_client=True,
                            send_server=True,
                            dist_time=rate)
                        dr.start()
                        dr.join()
                    else:
                        last_pos = (parser.LAST_X, parser.LAST_Y, parser.LAST_Z)
                        if None not in last_pos:
                            print 'injecting last position:', last_pos
                            coords.insert(0, last_pos)

                        dr = ReplayThread(
                            coords,
                            send_client=True,
                            send_server=False,
                            rate_limit=rate)
                        dr.start()
                        dr.join()
            elif cmd.startswith('saverec '):
                if parser.PLAYER_POS_HIST is not None:
                    filename = cmd[len('saverec '):]
                    with open(filename, 'w') as posfile:
                        posfile.write(json.dumps(parser.PLAYER_POS_HIST))
                        print 'Wrote recording to file %s' % (filename)
            elif cmd.startswith('loadrec '):
                filename = cmd[len('saverec '):]
                with open(filename, 'r') as posfile:
                    positions = json.loads(posfile.read())
                    parser.PLAYER_POS_HIST = positions
                    print 'Loaded file'
            elif cmd.startswith('emoji'):
                cmd = cmd.split(' ')
                emoji_id = int(cmd[-1], 0)
                pkt = parser.emoji_packet(emoji_id, CLIENT_SECRET)
                add_server_queue(encrypt_data(pkt))
            elif cmd == 'tfuzz':
                BLOCK_POSITION_OUT = True
                tf = TriggerFuzzThread(1.0)
                tf.start()
                tf.join()
                BLOCK_POSITION_OUT = False
            elif cmd == 'reload':
                reload(parser)
            else:
                pass
        except KeyboardInterrupt:
            print 'abort'
            continue
        except Exception as e:
            print e


if __name__ == '__main__':
    main()
