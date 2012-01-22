#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import logging

from itertools import chain
from collections import namedtuple
from struct import pack, unpack

import numpy as np
from operator import attrgetter, itemgetter, add
from collections import defaultdict
from itertools import permutations
from functools import partial

logging.basicConfig(level=logging.DEBUG)

Connection = namedtuple('Connection', 'ip_src port_src ip_dst port_dst rx_q tx_q')

class Connection(object):
    def __init__(self, ip_src, port_src, ip_dst=-1, port_dst=-1, rx_q=0, tx_q=0):
        self.ip_src = ip_src
        self.port_src = port_src
        self.ip_dst = ip_dst
        self.port_dst = port_dst
        self.rx_q = rx_q
        self.tx_q = tx_q

    def __repr__(self):
        return "Connection({0})".format(', '.join("{0}={1}".format(k, v) for k,v in self.__dict__.items()))

class Netstat(object):
    def __init__(self, connections=tuple()):
        """Constructs netstat object which represent IPv4/IPv6 connections of
        node"""
        self.connections = list()
        for connection in connections:
            self.add_connection(connection)

    def add_connection(self, connection):
        """Adds connection to set of connections"""
        self.connections.append(connection)

    def group_by_field(self, field, attributes='rx_q tx_q', func=add):
        """Returns connections grouped by @field using function @func"""
        groups = dict()
        for connection in self.connections:
            field_value = getattr(connection, field)
            if field_value in groups:
                for attr in attributes.split():
                    setattr(groups[field_value], attr, func(getattr(groups[field_value], attr), getattr(connection, attr)))
            else:
                groups[field_value] = connection
        return groups.values()

    def __getattribute__(self, name):
        """Wrapper for group_by_field methods"""
        group_by = 'group_by_'
        if name.startswith(group_by):
            return partial(object.__getattribute__(self, 'group_by_field'), field=name[len(group_by):])
        return object.__getattribute__(self, name)

def is_normal_connection(connection):
    """Returns True if connection looks ok, False otherwise"""
    if connection.ip_src in ['*', '127.0.0.1', '::1']:
        return False
    if connection.ip_src.startswith('fe8'):
        return False
    if connection.port_src == '*' or connection.port_dst == '*':
        return False
    return True

def parse_netstat_freebsd(lines):
    """Parse FreeBSD's ``netstat -anx`` output and yield Connection object"""
    first_line = lines.next()
    first_line = first_line.replace('Address', '').replace('-', '_').lower()
    first_line = " ".join(string.lstrip('1234567890') for string in first_line.split())

    FreeBSDNetstatEntry = namedtuple('FreeBSDNetstatEntry', first_line)
    netstat = Netstat()

    for line in lines:
        try:
            entry = FreeBSDNetstatEntry(*line.split())
        except Exception:
            logging.debug("Can't parse netstat line: {0}".format(line.strip()))
        try:
            ip_src, port_src = entry.local.rsplit('.', 1) 
            ip_dst, port_dst = entry.foreign.rsplit('.', 1) 
            connection = Connection(ip_src, port_src, ip_dst, port_dst, int(entry.r_bcnt), int(entry.s_bcnt))
            if is_normal_connection(connection):
                netstat.add_connection(connection)
        except Exception:
            logging.debug("Can't add connection to netstat: {0}".format(entry), exc_info=True)
    return netstat

def parse_netstat(filename):
    """Function wrapper that opens file, detects type of stats and pass to
    platform-spicific parser"""
    try:
        lines = open(filename)
        first_line = lines.next()
        if first_line.startswith('Active Internet connections'):
            return parse_netstat_freebsd(lines)
        elif first_line.startswith('  sl  '):
            raise NotImplementedError("Parsing of /proc/net/(tcp|udp)6? will come later")
            #return parse_netstat_linux(chain([first_line], lines))
        else:
            logging.warning("Can't determinate netstat type: {0}".format(first_line.strip()))
    except Exception:
        logging.error("Can't open and parse a file: {0}".format(filename), exc_info=True)

def netstat_to_gdf(netstat):
    nodedef = 'nodedef>name VARCHAR,label VARCHAR,class VARCHAR,dc VARCHAR\n'
    edgedef = 'edgedef>node1 VARCHAR,node2 VARCHAR,directed BOOLEAN,weight DOUBLE\n'

    for connection in netstat.group_by_ip_src():
        nodedef += '{0},{0},part_of_hostname,DC_from_yasubr\n'.format(connection.ip_src)
    for connection in netstat.connections:
        edgedef += '{0},{1},true,{2}\n'.format(connection.ip_src, connection.ip_dst, connection.rx_q + connection.tx_q)

    return nodedef + edgedef

from opster import command
@command()
def main(filenames,
        output=('o', 'output.gdf', 'file to append output')):
    for filename in filenames.split():
        print netstat_to_gdf(parse_netstat(filename))

if __name__ == '__main__':
    main.command()
