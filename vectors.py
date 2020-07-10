import math


def dist(u, v):
    return length(sub(v, u))


def dist_squared(u, v):
    return length_squared(sub(v, u))


def length_squared(u):
    return sum([a ** 2 for a in u])


def length(u):
    return math.sqrt(length_squared(u))


def scale_by_scalar(u, scalar):
    return [a * scalar for a in u]


def norm(u):
    return scale_by_scalar(u, 1.0 / length(u))


def add(u, v):
    return [a + b for a, b in zip(u, v)]


def sub(u, v):
    return [a - b for a, b in zip(u, v)]


def setlength(u, l):
    return scale_by_scalar(u, l / length(u))


def movetowards(pos, dest, stepsize):
    if dist(pos, dest) <= stepsize:
        return dest
    else:
        d = sub(dest, pos)
        d = setlength(d, stepsize)
        return add(pos, d)
