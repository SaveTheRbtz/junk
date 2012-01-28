Network graph
=============

About
~~~~~
This toolset converts ``netstat -an`` output from different hosts to graph
which can be processed by programs like `Gephi`_

``parse_netstat.py`` was written as attempt to prodide useful information about
Yandex's search cluster. Pretty visualizations are only side effects.

.. _Gephi: http://gephi.org/

Examples
~~~~~~~~
Simple example::

    $ netstat -an > test
    $ ./parse_netstat.py test

Or compressed one (currently only bzip2 named pipes are supported)::

    $ ./parse_netstat.py <(netstat -an | bzip2)


Or even bunch of samples::

    $ ./parse_netstat.py <(for i in {0..9}; do netstat -an; done | bzip2)


Or as did I, on large number of files obtained via some distributed collector
(I love `Cocaine`_!)::

    $ find stats/ -type f | xargs ./parse_netstat.py

This will produce sqlite3 database called by default ``graph.db`` in ``./output/``
directory.

.. _Cocaine: https://github.com/Kobolog/cocaine
