#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import socket

from collections import namedtuple, Counter

DC = dict()
# XXX(rbtz@): there is also state here, don't use it for now
NetstatEntry = namedtuple('NetstatEntry', 'proto recv_q send_q local foreign')

class Connection(object):
    def __init__(self, ip_src, port_src, ip_dst=-1, port_dst=-1, rx_q=0, tx_q=0, cnt=1):
        self.ip_src = ip_src
        self.port_src = port_src
        self.ip_dst = ip_dst
        self.port_dst = port_dst
        self.rx_q = rx_q
        self.tx_q = tx_q
        self.cnt = cnt

    def __repr__(self):
        return "Connection({0})".format(', '.join("{0}={1}".format(k, v) for k,v in self.__dict__.items()))

class Netstat(object):
    __doc__ = """netstat object represents IPv4/IPv6 connections of node"""
    def __init__(self, connections=tuple()):
        self.connections = list()
        for connection in connections:
            self.add_connection(connection)

    def add_connection(self, connection):
        """Adds connection to set of connections"""
        self.connections.append(connection)

def hostname(node):
    """Convert ip to full hostname"""
    try:
        return socket.gethostbyaddr(node)[0]
    except Exception:
        return ''

def short_hostname(node_name):
    """hostname -s"""
    return node_name.split('.')[0]

def is_normal_connection(connection):
    """Returns True if connection looks ok, False otherwise"""
    if connection.ip_src in ['*', '127.0.0.1', '::1']:
        return False
    if connection.ip_src.startswith('fe8') or connection.ip_src.startswith('10.'):
        return False
    if connection.ip_src.endswith(':') or connection.ip_dst.endswith(':'):
        return False
    if connection.port_src == '*' or connection.port_dst == '*':
        return False
    return True

def parse_netstat(lines):
    """Parse FreeBSD/Linux's ``netstat -an`` output and yield Connection object"""
    netstat = Netstat()

    separator = ':'
    for line in lines:
        try:
            entry = NetstatEntry(*line.split()[:5])
        except Exception:
            logging.debug("Can't parse netstat line: {0}".format(line.strip()))
            continue
        try:
            # FreeBSD separates port from ip with '.'
            if entry.local.count('.') in [4, 1]:
                separator = '.'
            ip_src, port_src = entry.local.rsplit(separator, 1)
            ip_dst, port_dst = entry.foreign.rsplit(separator, 1)
            connection = Connection(ip_src, port_src, ip_dst, port_dst, int(entry.recv_q), int(entry.send_q))
            if is_normal_connection(connection):
                netstat.add_connection(connection)
        except Exception:
            logging.debug("Can't add connection to netstat: {0}".format(entry))
    return netstat

def parse_input(filename):
    """
    Function wrapper that opens file, detects type of encoding and passes it
    line-by-line to netstat parser.

    FIXME(SaveTheRbtz@): Make it work with gzipped and plaintext pipes.
    """
    try:
        from gzip import GzipFile
        from bz2 import BZ2File
        first_line = ""
        for func in [BZ2File, GzipFile, open]:
            try:
                lines = func(filename)
                first_line = lines.next()
                break
            except:
                pass
        else:
            logging.error("Can't open file: {0}".format(filename), exc_info=True)
            return Netstat()
        if first_line.startswith('Active Internet connections'):
            return parse_netstat(lines)
        else:
            logging.warning("File does not seem to be a ``netstat -an`` output: {0}".format(first_line.strip()))
    except Exception:
        logging.error("Can't parse file: {0}".format(filename), exc_info=True)

def group_netstat(netstat):
    """Computes weights of connections (simply by counting them)"""
    output = dict(nodes=set(), edges=list())
    weights = Counter()

    for connection in netstat.connections:
        weights[(connection.ip_src, connection.ip_dst)] += 1
        for node in [connection.ip_src, connection.ip_dst]:
            output['nodes'].add(node)

    for ip_src, ip_dst in weights:
        # This is really ALOT of resolving. Should cache it somewhere... but am
        # an Admin, so just setup local unbound for now
        output['edges'].append((ip_src, ip_dst, weights[(ip_src, ip_dst)]))
    return output

def file_to_dict(filename):
    """Simple function composition"""
    try:
        return group_netstat(parse_input(filename))
    except Exception:
        logging.warning("Failed to parse: {0}".format(filename))
        return dict()

def cache_dc(dc_cache_filename):
    """
    Loads a file formated like::
        Data_Center_Name 0.0.0.0/0
    """
    try:
        global DC
        from ipaddr import IPv4Network
        with open(dc_cache_filename) as lines:
            for line in lines:
                dc_name, dc_net = line.split()[:2]
                DC[IPv4Network(dc_net)] = dc_name
        return True
    except Exception:
        logging.warning("Failed to load DC cache", exc_info=True)
        return False

def get_dc(ip):
    """Return IP's DC"""
    global DC
    if not DC:
        return ''
    try:
        from ipaddr import IPv4Address
        for dc_net, dc_name in DC.items():
            if IPv4Address(ip) in dc_net:
                return dc_name
    except Exception:
        logging.debug("Failed to load {0}'s DC from cache".format(ip), exc_info=True)
        return ''

def save_results(results, filename=''):
    """Save data to file"""
    if not filename:
        return False
    try:
        from sqlite3 import connect
        conn = connect(filename)
        c = conn.cursor()
        for result in results:
            for node in result.get('nodes', []):
                try:
                    c.execute('''insert into nodes values (?,?,?)''', (node, short_hostname(hostname(node)) or node, get_dc(node)))
                except Exception as e:
                    logging.info("Could not insert row in nodes table: {0}".format(e))
            for edge in result.get('edges', []):
                try:
                    c.execute('''insert into edges values (?,?,?)''', edge)
                except Exception as e:
                    logging.info("Could not insert row in edges table: {0}".format(e))
        conn.commit()
        c.close()
        return True
    except Exception:
        logging.warning("Can't save result to DB!", exc_info=True)
        return False

def prepare_database(filename):
    """Prepares database for usage"""
    from sqlite3 import connect
    conn = connect(filename)
    c = conn.cursor()
    c.execute("create table if not exists nodes (id string, label string, dc string)");
    c.execute("create unique index if not exists id_idx on nodes (id)");
    c.execute("create table if not exists edges (source string, target string, weight real)");
    conn.commit()
    c.close()

from opster import command
@command()
def main(output=('o', 'output/graph.db', 'sqlite database to put data to'),
        network_cache=('c', 'networks.txt', 'file with network layout partitioned by dc (optional)'),
        verbose=('v', False, 'be verbose'),
        *filenames):
    """Convert network statistics to GDF format"""

    severity=logging.WARNING
    if verbose:
        severity=logging.DEBUG
    logging.basicConfig(level=severity)

    prepare_database(output)
    cache_dc(network_cache)

    from multiprocessing import Pool
    pool = Pool()
    r = pool.map_async(file_to_dict, filenames)
    while not r.ready():
        save_results(r.get(), filename=output)

if __name__ == '__main__':
    main.command()
