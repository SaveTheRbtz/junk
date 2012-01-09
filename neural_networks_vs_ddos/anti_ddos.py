#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import logging

from itertools import chain
from collections import namedtuple

from pybrain.datasets            import ClassificationDataSet
from pybrain.utilities           import percentError
from pybrain.tools.shortcuts     import buildNetwork
from pybrain.supervised.trainers import BackpropTrainer
from pybrain.structure.modules   import SoftmaxLayer, SigmoidLayer, LinearLayer

from pybrain.tools.xml.networkwriter import NetworkWriter

import numpy as np
from itertools import permutations

from backports import lfu_cache
from urlparse import urlparse, parse_qs

from cPickle import dump, load

LogEntry = namedtuple('LogEntry', 'ip url code size refer useragent')
log = logging.getLogger('')
log.setLevel(logging.DEBUG)

def normalize_request(req):
    vectors = []
    try:
        method, url, http = req.split()
        vectors.append('__METHOD_' + method)
        vectors.extend(map(lambda x: "__URL_" + x, normalize_url(url)))
        vectors.append('__HTTP_VER_' + http)
    except Exception as e:
        log.debug("Broken request: {0}. Exc: {1}".format(req, e))
        return ['__BROKEN_REQ__']
    return map(lambda x: "__REQ_" + x, vectors)


@lfu_cache(maxsize=20000)
def normalize_url(url):
    vectors = []
    parsed_url = urlparse(url)
    vectors.append('__SCHEME_' + parsed_url.scheme)
    vectors.append('__NETLOC_' + parsed_url.netloc)
    if len(parsed_url.path) > 128:
        log.debug("url too long: {0}".format(parsed_url.path))
        vectors.append('__PATH_TOO_LONG')
    else:
        vectors.append('__PATH_' + parsed_url.path)
    if parsed_url.query:
        vectors.extend(map(lambda x: "__QS_" + x, normalize_qs(parsed_url.query)))
    return vectors


def normalize_qs(qs):
    """Just return query string argument keys"""
    qs_keys = parse_qs(qs).keys()
    if len(qs_keys) < 8:
        return parse_qs(qs).keys()
    else:
        log.debug("Too many keys in qs: {0}".format(qs))
        return ['TOO_MANY_KEYS']


@lfu_cache(maxsize=20000)
def normalize_refer(refer):
    """Apply normalize_url to refer"""
    if refer == '-':
        return [ '__NO_REFER__' ]
    return map(lambda x: "__REFER_" + x, normalize_url(refer))


@lfu_cache(maxsize=20000)
def normalize_ua(ua):
    """Parse and normalize User-Agent"""
    ua_regexp = re.compile(r'(?P<comp>[^ ]+)(?:\s+\((?P<os>[^)]+)\)(?:\s+(?P<version>.*))?)?')
    if ua == '-':
        return ['__UA_EMPTY']
    try:
        parsed_ua = ua_regexp.match(ua).groups()
    except Exception as e:
        log.debug("Broken UA: {0}".format(e))
        return ['__UA_BROKEN']
    try:
        base, os, version = parsed_ua
        vector = set()
        vector.add('__BASE_' + base)
        if not all([os, version]):
            return ['__UA_SIMPLE', '__UA_ONLY_BASE_' + base]
        if not version:
            vector.add('__NO_VERSION')
        vector |= set(map(lambda x: '__OS_' + x.strip(), os.split(';')))
        vector |= set(map(lambda x: '__VER_' + x.strip(' ()'), version.split()))
        #vector |= set("__".join(combined) for combined in permutations(vector, 2))
        return map(lambda x: "__UA_" + x, vector)
    except Exception as e:
        log.debug("Failed to parse UA: {0}".format(e))
        return ['__UA_BROKEN']


@lfu_cache(maxsize=200000)
def features_from_entry(entry):
    request = set(normalize_request(entry.url))
    refer = set(normalize_refer(entry.refer))
    useragent = set(normalize_ua(entry.useragent))
    try:
        code = set()
        if int(entry.code) in [503, 404, 403]:
            code.add('__CODE_' + entry.code)
    except Exception as e:
        log.debug("Failed to parse HTTP return code: {0}".format(e))
        pass
    return request | refer | useragent | code


def vector_from_entry(dictoinary, entry):
    return np.array([item in features_from_entry(entry) for item in dictionary])


def add_samples_to_training_set(training_set, file_name, label):
    with open(file_name) as file_:
        for line in file_:
            try:
                entry = LogEntry(*nginx_log_re.match(line).groups())
                training_set.addSample(list(vector_from_entry(dictionary, entry)), label)
            except Exception:
                log.error('Failed to parse line: {0}'.format(line), exc_info=True)


if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-g", "--good", dest="good_file",
                              help="nginx combined access log with good clients. For example access log before DDoS", metavar="FILE")
    parser.add_option("-b", "--bad", dest="bad_file",
                              help="nginx combined access log with bots' requests.", metavar="FILE")
    parser.add_option("-l", "--log", dest="log_file",
                              help="nginx combined access log for classification.", metavar="FILE")
    (options, args) = parser.parse_args()

    nginx_log_re = re.compile(r'(?P<ip>[0-9.:a-f]+) [^ ]+ [^ ]+ \[.*\] "(?P<url>.*)" (?P<code>[0-9]+) (?P<size>[0-9]+) "(?P<refer>.*)" "(?P<useragent>.*)"$')

    log.warning('Preparing dictionary')
    dictionary = set()
    with open(options.good_file) as good_file:
        with open(options.bad_file) as bad_file:
            for line in chain(good_file, bad_file):
                try: 
                    entry = LogEntry(*nginx_log_re.match(line).groups())
                    dictionary |= features_from_entry(entry)
                except Exception:
                    log.error('Failed to parse line: {0}'.format(line), exc_info=True)
    log.warning('Feature vector size: {0}'.format(len(dictionary)))
    dump(dictionary, open('dictionary.p', 'wb'))

    log.warning('Adding Samples')
    alldata = ClassificationDataSet(len(dictionary), 1, nb_classes=2, class_labels=['good','bad'])
    np.random.shuffle(alldata)
    add_samples_to_training_set(alldata, options.good_file, 0)
    add_samples_to_training_set(alldata, options.bad_file, 1)
   
    
    log.warning('Preparing data...')
    trndata, tstdata = alldata.splitWithProportion(0.60)

    for data in [trndata, tstdata]:
        data._convertToOneOfMany()

    tries = 5
    epochs = 5
    verbose = True

    previous_error = 100
    for _ in xrange(tries):
        log.warning('Constructing NeuralNetwork...')
        try_fnn = buildNetwork(trndata.indim, trndata.indim, trndata.outdim, hiddenclass=SigmoidLayer, outclass=SoftmaxLayer)

        log.warning('Training NeuralNetwork...')
        trainer = BackpropTrainer(try_fnn, dataset=trndata, momentum=0.1, verbose=verbose, weightdecay=0.01)
        trainer.trainEpochs(epochs)

        log.warning('Computing train and test errors...')
        trnresult = percentError(trainer.testOnClassData(), trndata['class'])
        tstresult = percentError(trainer.testOnClassData(dataset=tstdata ), tstdata['class'])
        print "epoch: %4d" % trainer.totalepochs, \
              "  train error: %5.2f%%" % trnresult, \
              "  test error: %5.2f%%" % tstresult
        if tstresult < previous_error:
            fnn = try_fnn
            previous_error = tstresult 

    NetworkWriter.writeToFile(fnn, 'nn.xml')

    log.warning('Activating NeuralNetwork...')
    nginx_log = ClassificationDataSet(len(dictionary), 1, nb_classes=2)
    add_samples_to_training_set(nginx_log, options.log_file, 0)
    nginx_log._convertToOneOfMany()  # this is still needed to make the fnn feel comfy

    out = fnn.activateOnDataset(nginx_log)
    out = out.argmax(axis=1)  # the highest output activation gives the class

    with open(options.log_file) as log_file:
        cnt = 0
        for line in log_file:
            try:
                entry = LogEntry(*nginx_log_re.match(line).groups())
                if out[cnt]:
                    print "BOT:  ",
                else:
                    print "GOOD: ",
                print "{0}".format(entry)
                cnt += 1
            except Exception:
                log.error('Failed to parse line: {0}'.format(line), exc_info=True)
