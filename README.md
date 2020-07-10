# maze-proxy

This is the UDP proxy I wrote to solve some of the challenges for the CSCG 2020 Maze
game hacking challenge. My writeup can be found [here](https://jamchamb.github.io/2020/06/21/cscg2020-maze-writeups.html).

The code is pretty messy and some things you may find useful are commented out, such as
print statements that describe incoming packet information, or the radar challenge solution
that records where the "White Rabbit" is.

The game proxy is implemented in `proxy.py` and `parser.py`. The code for plotting the White Rabbit
radar info on a graph is in `plot-wrt.py`, you can test it by running `./plot-wrt.py wr.txt`.

The recording I made of moving the rabbit from the start of the race to the end is `test1.json`.
You can replay it to beat the timed race challenge by running to the start of the race and running:

```
$ loadrec test1.json
$ playrec speed 500
```

Play around with the speed value to get a faster time. If it's not working you
won't see the "Race checkpoint: <id>" messages.

## Setup

First you will need to redirect the game to your proxy server. In my case I
set the host entry for `maze.liveoverflow.com` on my Windows host to the IP address
of the server I was running the proxy on (an Ubuntu VM). The Windows hosts file is found
at `C:\Windows\System32\drivers\etc\hosts`. I added this line:

```
192.168.182.133 maze.liveoverflow.com
```

Then you'll need to set up an HTTP proxy to forward the HTTP API traffic. I used Burp Suite
to achieve this. I redirected port 8080 to 80 on my Ubuntu VM (so that I wouldn't need to
run Burp as root) using the `80-to-8080.sh` script. Then I set up an invisible proxy bound
to `192.168.182.133:8080` in Burp, and created a match and replace rule to always replace
`1357` with `1337` in response bodies. This makes the game think that the only port available
to connect to is `1337`, which makes it easier to set up the UDP proxy.

The UDP game proxy is written for Python 2. Install dependencies with `pip install -r requirements.txt`
and then run it with `python2 proxy.py`. When you start the game and try to log in you should
see `Found game server maze.liveoverflow.com:1337-1337` at the bottom of the menu screen, and
then when you click "Login" you should start to see the packet hex dumps appear in the proxy
console. Type `v` and hit enter to toggle the verbosity and disable the packet dump view.

## Example commands

Here are some of the commands you can use; see the source code for the rest.

### v - verbosity
Enter `v` in the prompt to enable/disable the packet dumps and other
verbose prints.

### Recordings

* `startrec`: start recording position sent to server
* `stoprec`: stop recording position
* `saverec <filename>`: save recorded coordinates to a JSON file
* `loadrec <filename>`: load recorded coordinates from JSON file
* `playrec [rev] [rate_limit]`: replay recording (optionally in reverse), with given time between packets
* `playrec [rev] speed <units_per_second>`: replay recording (optionally in reverse),
  using the timestamp hack to scale up speed without getting kicked

### Emoji

* `emoji <int_id>`: Send emoji with given numeric ID (e.g. 16 = poop emoji)

### Teleport

* `T <x> <y> <z>`: Send server to client teleport command. You should run `bp` first
  to block the real server teleport packets so you don't just get rubber banded back
  to your original position. Type `bp` again to toggle position blocking off and return
  to the real position the server thinks you're at.
