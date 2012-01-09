#!/usr/bin/env python
import numpy as np
import matplotlib.pyplot as plt
from mdp.nodes import PCANode
from itertools import izip
from mpl_toolkits.mplot3d import Axes3D

def normalize(array):
    """Normalizes array row by row"""
    for row in array:
        mean = np.mean(row)
        std = np.std(row)
        row -= mean
        row /= std
    return array

def pca(multidim_data, output_dim):
    """Principal Component Analysis"""
    pcanode = PCANode(input_dim=multidim_data.shape[1], output_dim=output_dim, dtype=np.float32,
                      svd=True, reduce=True, var_rel=1E-15, var_abs=1E-15)
    pcanode.train(data)
    return np.dot(multidim_data, pcanode.get_projmatrix())

if __name__ == '__main__':
    import sys
    from dstat_csv_parser import parse_files
    from itertools import islice, imap
    fig = plt.figure()
    ax = fig.add_subplot(111)

    parsed_files = parse_files(sys.argv[1:])
    for f_id, parsed_data in enumerate(parsed_files):
        comments, header, startup = islice(parsed_data, 3)
        unnormalized_data = np.array(list(parsed_data))
        data = normalize(np.copy(unnormalized_data))
        projection = pca(data, output_dim=2)
        a = ax.scatter(projection[:,0], projection[:,1], s=20, c=xrange(projection.shape[0]), marker='o')
        for idx, row in enumerate(unnormalized_data):
            xy = projection[idx, :] + 0.0025
            #annotation = ''
            #for hdr in izip(header, imap(str, row)):
                #annotation += ":".join(hdr) + " "
            #print idx, " ", annotation
            import random
            if random.randint(0,10) == 0:
                plt.annotate(str(f_id), xy=xy)
    plt.show()
