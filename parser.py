import hexdump
import struct
import time
from threading import Lock
from util import encrypt_data, decrypt_data


#WHITERABBIT_FILE = open('wr.txt', 'a+')

SERVER_QUEUE = []
CLIENT_QUEUE = []

LAST_X, LAST_Y, LAST_Z = None, None, None

# Client time
LAST_TIME = None
LAST_TIME_NATIVE = None
TIME_OFFSET = None
CLI_TIME_LOCK = Lock()

# Server time
LAST_SRV_TICKS = 0
LAST_SRV_TIME = None
LAST_SRV_ROUNDTRIP = 0

# Temporary recording of player position
PLAYER_POS_HIST = None
RECORD_PLAYER_POS = False

INJECT_TIME = True
FREEZE_TIME = False
TIME_MULT = 1.0


def set_server_time(ticks, timestamp):
    global LAST_SRV_TIME, LAST_SRV_ROUNDTRIP
    global LAST_SRV_TICKS

    with CLI_TIME_LOCK:
        if LAST_SRV_TIME is not None:
            LAST_SRV_ROUNDTRIP = timestamp - LAST_SRV_TIME
        else:
            LAST_SRV_ROUNDTRIP = 0.0

            LAST_SRV_TIME = timestamp


def predict_server_time():
    global LAST_SRV_ROUNDTRIP
    with CLI_TIME_LOCK:
        result = time.time() + LAST_SRV_ROUNDTRIP

    return result


def set_client_time(timestamp, override_freeze=False):
    global LAST_TIME, LAST_TIME_NATIVE
    global FREEZE_TIME
    global TIME_OFFSET

    with CLI_TIME_LOCK:
        if FREEZE_TIME and LAST_TIME is not None and not override_freeze:
            return

        # Correct for time speedup shenanigans
        if TIME_OFFSET is not None:
            timestamp += TIME_OFFSET

        if timestamp < LAST_TIME:
            TIME_OFFSET = LAST_TIME - timestamp
            #print 'Updating time correction: offset = %f' % (TIME_OFFSET)

        LAST_TIME = timestamp
        LAST_TIME_NATIVE = time.time()


def predict_client_time():
    global LAST_TIME, LAST_TIME_NATIVE
    global FREEZE_TIME
    global TIME_MULT

    with CLI_TIME_LOCK:
        if LAST_TIME is None or LAST_TIME_NATIVE is None:
            return None

        if FREEZE_TIME:
            result = LAST_TIME
            return result

        result = LAST_TIME + ((time.time() - LAST_TIME_NATIVE) * 2)

        result *= TIME_MULT

    return result


def sign(n):
    if n < 0:
        return -1
    else:
        return 1


def emoji_packet(emoji_id, client_secret):
    pkt = 'E' + client_secret + struct.pack('<B', emoji_id)
    return pkt


def position_packet(secret, time_, x, y, z, eX, eY, eZ,
                    trigger, grounded, notGrounded,
                    raw_time=False):
    if len(secret) != 8:
        raise Exception('secret length != 8')

    pattern = '<QllllllBhh'

    x, y, z, eX, eY, eZ = map(
        lambda a: int(a * 10000.0),
        [x, y, z, eX, eY, eZ])

    if not raw_time:
        time_ = int(time_ * 10000.0)

    newData = struct.pack(
        pattern,
        time_, x, y, z, eX, eY, eZ, trigger, grounded, notGrounded)

    return 'P' + secret + newData


def teleport_packet(x, y, z, flag=1):
    x = int(x * 10000.0)
    y = int(y * 10000.0)
    z = int(z * 10000.0)
    data = 'T' + struct.pack('<Biii', flag, x, y, z)
    return data


def h_noop(data, origin):
    return data


def h_login(data, origin):
    print 'Login (%s)' % (origin)
    hexdump.hexdump(data)

    if origin == 'server':
        pattern = '<IHB'
        uid, unlocks, version = struct.unpack(
            pattern,
            data[1:1 + struct.calcsize(pattern)])
        print 'Logged in - UID: 0x%x, Unlocks: 0x%x, Version: %u' % (
            uid, unlocks, version)
        # Set all unlocks
        #forged = 'L' + struct.pack(
        #    pattern,
        #    uid, 0xffff, version)
        #return forged
    else:
        pattern = '<QB'
        patsize = struct.calcsize(pattern)
        secret, name_len = struct.unpack(pattern, data[1:1+patsize])
        name = data[1 + patsize:1 + patsize + name_len]
        print 'Logging in as %s, secret 0x%x' % (name, secret)

    return data


def h_heartbeat(data, origin):
    global LAST_TIME, LAST_SRV_TIME, LAST_SRV_ROUNDTRIP
    global INJECT_TIME

    if origin == 'client':
        # Client: 8 byte secret, 8 byte stamp
        secret, timestamp = struct.unpack('<QQ', data[2:])
        timestamp /= 10000.0

        set_client_time(timestamp)
        #print 'client time: %f, secret: %x' % (timestamp, secret)

        predicted = predict_client_time()
        if predicted is not None:
            #print 'Client time difference: %u' % (timestamp - predicted)

            # Inject proxy time
            if INJECT_TIME:
                # hackery
                if LAST_TIME > 0 and LAST_TIME < 0x8000000000000000:
                    inject_time = int(predicted * 10000)
                else:
                    inject_time = LAST_TIME
                newpkt = struct.pack(
                    '<QQ',
                    secret,
                    inject_time)
                return '<3' + newpkt
    else:
        # Server: Responds with tick time last sent by client, and unix
        # timestamp of when it was received
        ticks, timestamp = struct.unpack('<QQ', data[2:])
        ticks /= 10000.0
        timestamp /= 100.0

        set_server_time(ticks, timestamp)
        #print 'server time: %f, %f (%f roundtrip)' % (
        #    ticks,
        #    LAST_SRV_TIME, LAST_SRV_ROUNDTRIP)

    return data


def h_emoji(data, origin):
    if origin == 'client':
        emoji_id = struct.unpack('>B', data[-1:])[0]
        print 'send emoji: 0x%02x' % (emoji_id)
    else:
        uid, timestamp, emoji_id = struct.unpack('<LLB', data[1:])
        print 'recv emoji: player 0x%x, emoji 0x%x @ time %u' % (
            uid, emoji_id, timestamp)

    return data


def h_position(data, origin):
    global LAST_X, LAST_Y, LAST_Z, LAST_TIME
    global RECORD_PLAYER_POS, PLAYER_POS_HIST

    if origin == 'client':
        # Skip key, tag, and secret
        secret = data[1:9]
        payload = data[9:]
        pattern = '<qllllllBhh'
        time_, x, y, z, eX, eY, eZ, \
            trigger, grounded, notGrounded = struct.unpack(
                pattern, payload[:struct.calcsize(pattern)])
        x, y, z, eX, eY, eZ = map(
            lambda a: float(a) / 10000.0,
            [x, y, z, eX, eY, eZ])

        time_ /= 10000.0

        #print 'Position (client->server):\nTime:{} X: {} ({}), Y: {} ({}), Z: {} ({}) Trigger: {} ground: {} notground {}'.format(
        #    time_, x, eX, y, eY, z, eZ, trigger, grounded, notGrounded)
        #print 'Position time:', time_

        # Update client time
        set_client_time(time_)

        if RECORD_PLAYER_POS:
            if PLAYER_POS_HIST is None:
                PLAYER_POS_HIST = []
            PLAYER_POS_HIST.append((x, y, z))

        LAST_X = x
        LAST_Y = y
        LAST_Z = z

        if INJECT_TIME:
            predicted = predict_client_time()
            if predicted is not None:
                #print 'Position injected time:', predicted
                time_ = predicted

        newData = position_packet(secret, time_, x, y, z, eX, eY, eZ,
                                  trigger, grounded, notGrounded)

        return newData
    else:
        return data  # HACK: skip for latency in race challenge
        #print 'Position (server->client)'
        # UID, timestamp, x, y, z, eX, eY, eZ, ground, notground?
        pattern = '<IQiiiiiiBhh'
        payload = data[1:]
        patsize = struct.calcsize(pattern)

        while len(payload) >= patsize:
            uid, timestamp, x, y, z, eX, eY, eZ, trigger, ground, notground = struct.unpack(pattern, payload[:patsize])
            x, y, z, eX, eY, eZ = map(
                lambda a: float(a) / 10000.0,
                [x, y, z, eX, eY, eZ])
            #print 'UID %x @ %u: %f, %f, %f, %x, %x, %x' % (
            #    uid, timestamp,
            #    x, y, z,
            #    trigger, ground, notground)

            # write white rabbit coords
            #if uid == 0xffff1337:
            #    WHITERABBIT_FILE.write(
            #        '%f,%f,%f,%f,%f,%f\n' % (x, y, z, eX, eY, eZ))

            payload = payload[patsize:]
            if len(payload) > 0 and payload[0] != 'P':
                break
            payload = payload[1:]

        return data


def h_info(data, origin):
    if origin == 'server':
        pattern = '<IHB'
        uid, b, name_len = struct.unpack(
            pattern,
            data[1:1 + struct.calcsize(pattern)])
        name = data[1 + struct.calcsize(pattern):]
        #print 'Info: "%s", %x, %x' % (name, uid, b)

    return data


def h_teleport(data, origin):
    unk, x, y, z = struct.unpack('<Biii', data[1:])
    x /= 10000.0
    y /= 10000.0
    z /= 10000.0
    print 'TELEPORT (%s): 0x%x, %f %f %f' % (
        origin, unk, x, y, z)
    return data


def h_race(data, origin):
    if origin == 'server':
        chkId = struct.unpack('<B', data[1])[0]
        print '***Race checkpoint: 0x%x' % (chkId)

    return data


def h_unlock(data, origin):
    if origin == 'server':
        unlocks = struct.unpack('<H', data[1:])[0]
        print 'unlocks: 0x%x' % (unlocks)

    return data


def h_freeze(data, origin):
    print 'got freeze msg'
    return data


def h_logout(data, origin):
    print 'got forced logout'
    return data


def h_death(data, origin):
    print 'got death'
    return data


def h_flag(data, origin):
    # flag starts with CSCG
    print 'got flag', data

    return data


handlers = {
    '<': h_heartbeat,
    'E': h_emoji,
    'P': h_position,
    'L': h_login,
    'I': h_info,
    'T': h_teleport,
    'R': h_race,
    'X': h_logout,
    'Y': h_freeze,
    'D': h_death,
    'C': h_flag,
}


def parse(data, port, origin):

    if data[0] in handlers:
        data = handlers[data[0]](data, origin)

    if data is not None:
        if origin == 'client':
            SERVER_QUEUE.append(data)
        else:
            CLIENT_QUEUE.append(data)
