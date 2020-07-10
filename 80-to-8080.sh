#!/bin/bash
iptables -A INPUT -i ens33 -p tcp --dport 80 -j ACCEPT

iptables -A INPUT -i ens33 -p tcp --dport 8080 -j ACCEPT

iptables -A PREROUTING -t nat -i ens33 -p tcp --dport 80 -j REDIRECT --to-port 8080
