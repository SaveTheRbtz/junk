#!/usr/bin/env python
from itertools import islice, izip, takewhile


def parse_files(files):
    fds = (open(file) for file in files)
    return [parse_stream(fd) for fd in fds]


def parse_stream(stream):
    import csv
    rows = csv.reader(stream, delimiter=',', quotechar='"')
    # Strip dstat header
    yield list(takewhile(bool, rows))
    # Denormalize 2-row header
    hdr_rows = list(islice(rows, 0, 2))
    for i, value in enumerate(hdr_rows[0]):
        if not value:
            hdr_rows[0][i] = hdr_rows[0][i - 1]
    yield ["/".join(x) for x in izip(*hdr_rows)]
    # Convert data to float
    # 1-st row is data since uptime
    for row in rows:
        yield [ float(value) for value in row ]

if __name__ == '__main__':
    import fileinput
    print list(parse_stream(fileinput.input()))
