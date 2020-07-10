#!/usr/bin/env python2
import argparse
import json
import matplotlib.pyplot as plt


def load_txt(txt_file):
    x_coords = []
    y_coords = []

    wrf_lines = [l.rstrip('\n') for l in txt_file.readlines()]
    for line in wrf_lines:
        try:
            x, y, z, eX, eY, eZ = (float(a) for a in line.split(','))
            x_coords.append(x)
            y_coords.append(z)
        except:
            pass

    return (x_coords, y_coords)


def load_json(json_file):
    x_coords = []
    y_coords = []

    entries = json.loads(json_file.read())

    for entry in entries:
        x_coords.append(entry[0])
        y_coords.append(entry[2])

    return (x_coords, y_coords)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pointfile', type=str)
    args = parser.parse_args()

    wrf = open(args.pointfile, 'r')

    if args.pointfile.endswith('.txt'):
        x_coords, y_coords = load_txt(wrf)
    elif args.pointfile.endswith('.json'):
        x_coords, y_coords = load_json(wrf)
    else:
        raise Exception('unhandled file type')

    print 'Loaded %u lines' % (len(x_coords))

    plt.plot(x_coords, y_coords, 'ro', ms=0.5)
    plt.axis([0, 400, 0, 400])
    plt.show()


if __name__ == '__main__':
    main()
