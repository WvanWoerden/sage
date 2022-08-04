r"""
Zariski-Van Kampen method implementation

This file contains functions to compute the fundamental group of
the complement of a curve in the complex affine or projective plane,
using Zariski-Van Kampen approach. It depends on the package ``sirocco``.

The current implementation allows to compute a presentation of the
fundamental group of curves over the rationals or number fields with
a fixed embedding on `\QQbar`.

Instead of computing a representation of the braid monodromy, we
choose several base points and a system of paths joining them that
generate all the necessary loops around the points of the discriminant.
The group is generated by the free groups over these points, and
braids over this paths gives relations between these generators.
This big group presentation is simplified at the end.

AUTHORS:

- Miguel Marco (2015-09-30): Initial version

EXAMPLES::

    sage: from sage.schemes.curves.zariski_vankampen import fundamental_group # optional - sirocco
    sage: R.<x,y> = QQ[]
    sage: f = y^3 + x^3 -1
    sage: fundamental_group(f) # optional - sirocco
    Finitely presented group < x0 |  >
"""
# ****************************************************************************
#       Copyright (C) 2015 Miguel Marco <mmarco@unizar.es>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#                  https://www.gnu.org/licenses/
# ****************************************************************************

from sage.groups.braid import BraidGroup
from sage.groups.perm_gps.permgroup_named import SymmetricGroup
from sage.rings.rational_field import QQ
from sage.rings.qqbar import QQbar
from sage.parallel.decorate import parallel
from sage.misc.flatten import flatten
from sage.groups.free_group import FreeGroup
from sage.misc.misc_c import prod
from sage.rings.complex_mpfr import ComplexField
from sage.rings.real_mpfr import RealField
from sage.rings.complex_interval_field import ComplexIntervalField
from sage.combinat.permutation import Permutation
import itertools
from sage.geometry.voronoi_diagram import VoronoiDiagram
from sage.graphs.graph import Graph
from sage.misc.cachefunc import cached_function
from copy import copy


roots_interval_cache = dict()


def braid_from_piecewise(strands):
    r"""
    Compute the braid corresponding to the piecewise linear curves strands.

    INPUT:

    - ``strands`` -- a list of lists of tuples ``(t, c1, c2)``, where ``t``
      is a number between 0 and 1, and ``c1`` and ``c2`` are rationals or algebraic reals.

    OUTPUT:

    The braid formed by the piecewise linear strands.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import braid_from_piecewise # optional - sirocco
        sage: paths = [[(0, 0, 1), (0.2, -1, -0.5), (0.8, -1, 0), (1, 0, -1)],
        ....:          [(0, -1, 0), (0.5, 0, -1), (1, 1, 0)],
        ....:          [(0, 1, 0), (0.5, 1, 1), (1, 0, 1)]]
        sage: braid_from_piecewise(paths) # optional - sirocco
        s0*s1
    """
    L = strands
    i = min(val[1][0] for val in L)
    totalpoints = [[[a[0][1], a[0][2]]] for a in L]
    indices = [1 for a in range(len(L))]
    while i < 1:
        for j, val in enumerate(L):
            if val[indices[j]][0] > i:
                xauxr = val[indices[j] - 1][1]
                xauxi = val[indices[j] - 1][2]
                yauxr = val[indices[j]][1]
                yauxi = val[indices[j]][2]
                aaux = val[indices[j] - 1][0]
                baux = val[indices[j]][0]
                interpolar = xauxr + (yauxr - xauxr) * (i - aaux) / (baux - aaux)
                interpolai = xauxi + (yauxi - xauxi) * (i - aaux) / (baux - aaux)
                totalpoints[j].append([interpolar, interpolai])
            else:
                totalpoints[j].append([val[indices[j]][1],
                                       val[indices[j]][2]])
                indices[j] = indices[j] + 1
        i = min(val[indices[k]][0] for k, val in enumerate(L))

    for j, val in enumerate(L):
        totalpoints[j].append([val[-1][1], val[-1][2]])
    braid = []
    G = SymmetricGroup(len(totalpoints))

    def sgn(x, y):
        if x < y:
            return 1
        if x > y:
            return -1
        return 0
    for i in range(len(totalpoints[0]) - 1):
        l1 = [totalpoints[j][i] for j in range(len(L))]
        l2 = [totalpoints[j][i + 1] for j in range(len(L))]
        M = [[l1[s], l2[s]] for s in range(len(l1))]
        M.sort()
        l1 = [a[0] for a in M]
        l2 = [a[1] for a in M]
        cruces = []
        for j in range(len(l2)):
            for k in range(j):
                if l2[j] < l2[k]:
                    t = (l1[j][0] - l1[k][0])/((l2[k][0]-l2[j][0]) + (l1[j][0] - l1[k][0]))
                    s = sgn(l1[k][1]*(1 - t) + t*l2[k][1], l1[j][1]*(1 - t) + t*l2[j][1])
                    cruces.append([t, k, j, s])
        if cruces:
            cruces.sort()
            P = G(Permutation([]))
            while cruces:
                # we select the crosses in the same t
                crucesl = [c for c in cruces if c[0] == cruces[0][0]]
                crossesl = [(P(c[2] + 1) - P(c[1] + 1), c[1], c[2], c[3])
                            for c in crucesl]
                cruces = cruces[len(crucesl):]
                while crossesl:
                    crossesl.sort()
                    c = crossesl.pop(0)
                    braid.append(c[3]*min(map(P, [c[1] + 1, c[2] + 1])))
                    P = G(Permutation([(c[1] + 1, c[2] + 1)])) * P
                    crossesl = [(P(cr[2]+1) - P(cr[1]+1), cr[1], cr[2], cr[3])
                                for cr in crossesl]

    B = BraidGroup(len(L))
    return B(braid)


def discrim(f):
    r"""
    Return the points in the discriminant of ``f``.

    The result is the set of values of the first variable for which
    two roots in the second variable coincide.

    INPUT:

    - ``f`` -- a polynomial in two variables with coefficients in a
      number field with a fixed embedding in `\QQbar`

    OUTPUT:

    A list with the values of the discriminant in `\QQbar`.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import discrim
        sage: R.<x,y> = QQ[]
        sage: f = (y^3 + x^3 - 1) * (x + y)
        sage: discrim(f)
        [1,
        -0.500000000000000? - 0.866025403784439?*I,
        -0.500000000000000? + 0.866025403784439?*I]
    """
    x, y = f.parent().gens()
    F = f.base_ring()
    poly = F[x](f.discriminant(y)).radical()
    return poly.roots(QQbar, multiplicities=False)


@cached_function
def corrected_voronoi_diagram(points):
    r"""
    Compute a Voronoi diagram of a set of points with rational coordinates, such
    that the given points are granted to lie one in each bounded region.

    INPUT:

    - ``points`` -- a list of complex numbers

    OUTPUT:

    A VoronoiDiagram constructed from rational approximations of the points,
    with the guarantee that each bounded region contains exactly one of the
    input points.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import corrected_voronoi_diagram
        sage: points = (2, I, 0.000001, 0, 0.000001*I)
        sage: V = corrected_voronoi_diagram(points)
        sage: V
        The Voronoi diagram of 9 points of dimension 2 in the Rational Field
        sage: V.regions()
        {P(-7, 0): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 4 vertices and 2 rays,
        P(0, -7): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 4 vertices and 2 rays,
        P(0, 0): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 4 vertices,
        P(0, 1): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 5 vertices,
        P(0, 1/1000000): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 4 vertices,
        P(0, 7): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 3 vertices and 2 rays,
        P(1/1000000, 0): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 5 vertices,
        P(2, 0): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 5 vertices,
        P(7, 0): A 2-dimensional polyhedron in QQ^2 defined as the convex hull of 2 vertices and 2 rays}

    """
    prec = 53
    point_coordinates = [(p.real(), p.imag()) for p in points]
    while True:
        RF = RealField(prec)
        apprpoints = {(QQ(RF(p[0])), QQ(RF(p[1]))): p for p in point_coordinates}
        added_points = 3 * max(map(abs, flatten(apprpoints))) + 1
        configuration = list(apprpoints.keys())+[(added_points, 0),
                                                 (-added_points, 0),
                                                 (0, added_points),
                                                 (0, -added_points)]
        V = VoronoiDiagram(configuration)
        valid = True
        for r in V.regions().items():
            if not r[1].rays() and not r[1].interior_contains(apprpoints[r[0].affine()]):
                prec += 53
                valid = False
                break
        if valid:
            break
    return V


def segments(points):
    """
    Return the bounded segments of the Voronoi diagram of the given points.

    INPUT:

    - ``points`` -- a list of complex points

    OUTPUT:

    A list of pairs ``(p1, p2)``, where ``p1`` and ``p2`` are the
    endpoints of the segments in the Voronoi diagram.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import discrim, segments
        sage: R.<x,y> = QQ[]
        sage: f = y^3 + x^3 - 1
        sage: disc = discrim(f)
        sage: sorted(segments(disc))
        [(-192951821525958031/67764026159052316*I - 192951821525958031/67764026159052316,
          -192951821525958031/90044183378780414),
         (-192951821525958031/67764026159052316*I - 192951821525958031/67764026159052316,
          -144713866144468523/66040650000519163*I + 167101179147960739/132081300001038326),
         (192951821525958031/67764026159052316*I - 192951821525958031/67764026159052316,
          144713866144468523/66040650000519163*I + 167101179147960739/132081300001038326),
         (-192951821525958031/90044183378780414,
          192951821525958031/67764026159052316*I - 192951821525958031/67764026159052316),
         (-192951821525958031/90044183378780414, 1/38590364305191606),
         (1/38590364305191606,
          -144713866144468523/66040650000519163*I + 167101179147960739/132081300001038326),
         (1/38590364305191606,
          144713866144468523/66040650000519163*I + 167101179147960739/132081300001038326),
         (-5/2*I + 5/2,
          -144713866144468523/66040650000519163*I + 167101179147960739/132081300001038326),
         (-5/2*I + 5/2, 5/2*I + 5/2),
         (5/2*I + 5/2,
          144713866144468523/66040650000519163*I + 167101179147960739/132081300001038326)]

    """
    V = corrected_voronoi_diagram(tuple(points))
    res = set([])
    for region in V.regions().values():
        if region.rays():
            continue
        segments = region.facets()
        for s in segments:
            t = tuple((tuple(v.vector()) for v in s.vertices()))
            if t not in res and not tuple(reversed(t)) in res:
                res.add(t)
    return [(r[0]+QQbar.gen()*r[1], s[0]+QQbar.gen()*s[1]) for (r, s) in res]


def followstrand(f, factors, x0, x1, y0a, prec=53):
    r"""
    Return a piecewise linear approximation of the homotopy continuation
    of the root ``y0a`` from ``x0`` to ``x1``.

    INPUT:

    - ``f`` -- an irreducible polynomial in two variables
    - ``factors`` -- a list of irreducible polynomials in two variables
    - ``x0`` -- a complex value, where the homotopy starts
    - ``x1`` -- a complex value, where the homotopy ends
    - ``y0a`` -- an approximate solution of the polynomial `F(y) = f(x_0, y)`
    - ``prec`` -- the precision to use

    OUTPUT:

    A list of values `(t, y_{tr}, y_{ti})` such that:

    - ``t`` is a real number between zero and one
    - `f(t \cdot x_1 + (1-t) \cdot x_0, y_{tr} + I \cdot y_{ti})`
      is zero (or a good enough approximation)
    - the piecewise linear path determined by the points has a tubular
      neighborhood  where the actual homotopy continuation path lies, and
      no other root of ``f``, nor any root of the polynomials in ``factors``,
      intersects it.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import followstrand # optional - sirocco
        sage: R.<x,y> = QQ[]
        sage: f = x^2 + y^3
        sage: x0 = CC(1, 0)
        sage: x1 = CC(1, 0.5)
        sage: followstrand(f, [], x0, x1, -1.0) # optional - sirocco # abs tol 1e-15
        [(0.0, -1.0, 0.0),
         (0.7500000000000001, -1.015090921153253, -0.24752813818386948),
         (1.0, -1.026166099551513, -0.32768940253604323)]
        sage: fup = f.subs({y:y-1/10})
        sage: fdown = f.subs({y:y+1/10})
        sage: followstrand(f, [fup, fdown], x0, x1, -1.0) # optional - sirocco # abs tol 1e-15
        [(0.0, -1.0, 0.0),
         (0.5303300858899107, -1.0076747107983448, -0.17588022709184917),
         (0.7651655429449553, -1.015686131039112, -0.25243563967299404),
         (1.0, -1.026166099551513, -0.3276894025360433)]

    """
    if f.degree() == 1:
        CF = ComplexField(prec)
        g = f.change_ring(CF)
        (x, y) = g.parent().gens()
        y0 = CF[y](g.subs({x: x0})).roots()[0][0]
        y1 = CF[y](g.subs({x: x1})).roots()[0][0]
        res = [(0.0, y0.real(), y0.imag()), (1.0, y1.real(), y1.imag())]
        return res
    CIF = ComplexIntervalField(prec)
    CC = ComplexField(prec)
    G = f.change_ring(QQbar).change_ring(CIF)
    (x, y) = G.parent().gens()
    g = G.subs({x: (1 - x) * CIF(x0) + x * CIF(x1)})
    coefs = []
    deg = g.total_degree()
    for d in range(deg + 1):
        for i in range(d + 1):
            c = CIF(g.coefficient({x: d - i, y: i}))
            cr = c.real()
            ci = c.imag()
            coefs += list(cr.endpoints())
            coefs += list(ci.endpoints())
    yr = CC(y0a).real()
    yi = CC(y0a).imag()
    coefsfactors = []
    degsfactors = []
    for fc in factors:
        degfc = fc.degree()
        degsfactors.append(degfc)
        G = fc.change_ring(QQbar).change_ring(CIF)
        g = G.subs({x: (1 - x) * CIF(x0) + x * CIF(x1)})
        for d in range(degfc + 1):
            for i in range(d + 1):
                c = CIF(g.coefficient({x: d - i, y: i}))
                cr = c.real()
                ci = c.imag()
                coefsfactors += list(cr.endpoints())
                coefsfactors += list(ci.endpoints())
    from sage.libs.sirocco import contpath, contpath_mp, contpath_comps, contpath_mp_comps
    try:
        if prec == 53:
            if factors:
                points = contpath_comps(deg, coefs, yr, yi, degsfactors, coefsfactors)
            else:
                points = contpath(deg, coefs, yr, yi)
        else:
            if factors:
                points = contpath_mp_comps(deg, coefs, yr, yi, prec, degsfactors, coefsfactors)
            else:
                points = contpath_mp(deg, coefs, yr, yi, prec)
        return points
    except Exception:
        return followstrand(f, factors, x0, x1, y0a, 2 * prec)


def newton(f, x0, i0):
    r"""
    Return the interval Newton operator.

    INPUT:

    - ``f``` -- a univariate polynomial
    - ``x0`` -- a number
    - ``I0`` -- an interval

    OUTPUT:

    The interval `x_0-\frac{f(x_0)}{f'(I_0)}`


    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import newton
        sage: R.<x> = QQbar[]
        sage: f = x^3 + x
        sage: x0 = 1/10
        sage: I0 = RIF((-1/5,1/5))
        sage: n = newton(f, x0, I0)
        sage: n
        0.0?
        sage: n.real().endpoints()
        (-0.0147727272727274, 0.00982142857142862)
        sage: n.imag().endpoints()
        (0.000000000000000, -0.000000000000000)

    """
    return x0 - f(x0)/f.derivative()(i0)


@parallel
def roots_interval(f, x0):
    """
    Find disjoint intervals that isolate the roots of a polynomial for a fixed
    value of the first variable.

    INPUT:

    - ``f`` -- a bivariate squarefree polynomial
    - ``x0`` -- a value where the first coordinate will be fixed

    The intervals are taken as big as possible to be able to detect when two
    approximate roots of `f(x_0, y)` correspond to the same exact root.

    The result is given as a dictionary, where the keys are approximations to the roots
    with rational real and imaginary parts, and the values are intervals containing them.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import roots_interval
        sage: R.<x,y> = QQ[]
        sage: f = y^3 - x^2
        sage: ri = roots_interval(f, 1)
        sage: ri
        {-138907099/160396102*I - 1/2: -1.? - 1.?*I,
         138907099/160396102*I - 1/2: -1.? + 1.?*I,
         1: 1.? + 0.?*I}
        sage: [r.endpoints() for r in ri.values()]
        [(0.566987298107781 - 0.433012701892219*I,
          1.43301270189222 + 0.433012701892219*I,
          0.566987298107781 + 0.433012701892219*I,
          1.43301270189222 - 0.433012701892219*I),
         (-0.933012701892219 - 1.29903810567666*I,
          -0.0669872981077806 - 0.433012701892219*I,
          -0.933012701892219 - 0.433012701892219*I,
          -0.0669872981077806 - 1.29903810567666*I),
         (-0.933012701892219 + 0.433012701892219*I,
          -0.0669872981077806 + 1.29903810567666*I,
          -0.933012701892219 + 1.29903810567666*I,
          -0.0669872981077806 + 0.433012701892219*I)]

    """
    x, y = f.parent().gens()
    I = QQbar.gen()
    fx = QQbar[y](f.subs({x: QQ(x0.real())+I*QQ(x0.imag())}))
    roots = fx.roots(QQbar, multiplicities=False)
    result = {}
    for i in range(len(roots)):
        r = roots[i]
        prec = 53
        IF = ComplexIntervalField(prec)
        CF = ComplexField(prec)
        divisor = 4
        diam = min((CF(r)-CF(r0)).abs() for r0 in roots[:i]+roots[i+1:]) / divisor
        envelop = IF(diam)*IF((-1, 1), (-1, 1))
        while not newton(fx, r, r+envelop) in r+envelop:
            prec += 53
            IF = ComplexIntervalField(prec)
            CF = ComplexField(prec)
            divisor *= 2
            diam = min([(CF(r)-CF(r0)).abs() for r0 in roots[:i]+roots[i+1:]])/divisor
            envelop = IF(diam)*IF((-1, 1), (-1, 1))
        qapr = QQ(CF(r).real())+QQbar.gen()*QQ(CF(r).imag())
        if qapr not in r+envelop:
            raise ValueError("Could not approximate roots with exact values")
        result[qapr] = r+envelop
    return result


def roots_interval_cached(f, x0):
    r"""
    Cached version of :func:`roots_interval`.


    TESTS::

        sage: from sage.schemes.curves.zariski_vankampen import roots_interval, roots_interval_cached, roots_interval_cache
        sage: R.<x,y> = QQ[]
        sage: f = y^3 - x^2
        sage: (f, 1) in roots_interval_cache
        False
        sage: ri = roots_interval_cached(f, 1)
        sage: ri
        {-138907099/160396102*I - 1/2: -1.? - 1.?*I,
         138907099/160396102*I - 1/2: -1.? + 1.?*I,
         1: 1.? + 0.?*I}
        sage: (f, 1) in roots_interval_cache
        True

    """
    global roots_interval_cache
    try:
        return roots_interval_cache[(f, x0)]
    except KeyError:
        result = roots_interval(f, x0)
        roots_interval_cache[(f, x0)] = result
        return result


def populate_roots_interval_cache(inputs):
    r"""
    Call :func:`roots_interval` to the inputs that have not been
    computed previously, and cache them.

    INPUT:

    - ``inputs`` -- a list of tuples (f, x0)

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import populate_roots_interval_cache, roots_interval_cache
        sage: R.<x,y> = QQ[]
        sage: f = y^5 - x^2
        sage: (f, 3) in roots_interval_cache
        False
        sage: populate_roots_interval_cache([(f, 3)])
        sage: (f, 3) in roots_interval_cache
        True
        sage: roots_interval_cache[(f, 3)]
        {-1.255469441943070? - 0.9121519421827974?*I: -2.? - 1.?*I,
         -1.255469441943070? + 0.9121519421827974?*I: -2.? + 1.?*I,
         0.4795466549853897? - 1.475892845355996?*I: 1.? - 2.?*I,
         0.4795466549853897? + 1.475892845355996?*I: 1.? + 2.?*I,
         14421467174121563/9293107134194871: 2.? + 0.?*I}

    """
    global roots_interval_cache
    tocompute = [inp for inp in inputs if inp not in roots_interval_cache]
    result = roots_interval(tocompute)
    for r in result:
        roots_interval_cache[r[0][0]] = r[1]


@parallel
def braid_in_segment(g, x0, x1):
    """
    Return the braid formed by the `y` roots of ``f`` when `x` moves
    from ``x0`` to ``x1``.

    INPUT:

    - ``g`` -- a polynomial factorization in two variables
    - ``x0`` -- a complex number
    - ``x1`` -- a complex number

    OUTPUT:

    A braid.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import braid_in_segment # optional - sirocco
        sage: R.<x,y> = QQ[]
        sage: f = x^2 + y^3
        sage: x0 = CC(1,0)
        sage: x1 = CC(1, 0.5)
        sage: braid_in_segment(f.factor(), x0, x1) # optional - sirocco
        s1

    TESTS:

    Check that :trac:`26503` is fixed::

        sage: wp = QQ['t']([1, 1, 1]).roots(QQbar)[0][0]
        sage: Kw.<wp> = NumberField(wp.minpoly(), embedding=wp)
        sage: R.<x, y> = Kw[]
        sage: z = -wp - 1
        sage: f = y*(y + z)*x*(x - 1)*(x - y)*(x + z*y - 1)*(x + z*y + wp)
        sage: from sage.schemes.curves import zariski_vankampen as zvk
        sage: g = f.subs({x: x + 2*y})
        sage: p1 = QQbar(sqrt(-1/3))
        sage: p2 = QQbar(1/2+sqrt(-1/3)/2)
        sage: B = zvk.braid_in_segment(g.factor(),CC(p1),CC(p2)) # optional - sirocco
        sage: B  # optional - sirocco
        s5*s3^-1

    """
    (x, y) = g.value().parent().gens()
    I = QQbar.gen()
    X0 = QQ(x0.real()) + I * QQ(x0.imag())
    X1 = QQ(x1.real()) + I * QQ(x1.imag())
    intervals = {}
    precision = {}
    y0s = []
    for (f, naux) in g:
        if f.variables() == (y,):
            F0 = QQbar[y](f.base_ring()[y](f))
        else:
            F0 = QQbar[y](f(X0, y))
        y0sf = F0.roots(multiplicities=False)
        y0s += list(y0sf)
        precision[f] = 53
        while True:
            CIFp = ComplexIntervalField(precision[f])
            intervals[f] = [r.interval(CIFp) for r in y0sf]
            if not any(a.overlaps(b) for a, b in itertools.combinations(intervals[f], 2)):
                break
            precision[f] *= 2
    strands = [followstrand(f[0], [p[0] for p in g if p[0] != f[0]], x0, x1, i.center(), precision[f[0]]) for f in g for i in intervals[f[0]]]
    complexstrands = [[(QQ(a[0]), QQ(a[1]), QQ(a[2])) for a in b] for b in strands]
    centralbraid = braid_from_piecewise(complexstrands)
    initialstrands = []
    finalstrands = []
    initialintervals = roots_interval_cached(g.value(), X0)
    finalintervals = roots_interval_cached(g.value(), X1)
    for cs in complexstrands:
        ip = cs[0][1] + I*cs[0][2]
        fp = cs[-1][1] + I*cs[-1][2]
        matched = 0
        for center, interval in initialintervals.items():
            if ip in interval:
                initialstrands.append([(0, center.real(), center.imag()), (1, cs[0][1], cs[0][2])])
                matched += 1
        if matched == 0:
            raise ValueError("unable to match braid endpoint with root")
        if matched > 1:
            raise ValueError("braid endpoint mathes more than one root")
        matched = 0
        for center, interval in finalintervals.items():
            if fp in interval:
                finalstrands.append([(0, cs[-1][1], cs[-1][2]), (1, center.real(), center.imag())])
                matched += 1
        if matched == 0:
            raise ValueError("unable to match braid endpoint with root")
        if matched > 1:
            raise ValueError("braid endpoint mathes more than one root")
    initialbraid = braid_from_piecewise(initialstrands)
    finalbraid = braid_from_piecewise(finalstrands)

    return initialbraid * centralbraid * finalbraid


def orient_circuit(circuit):
    r"""
    Reverses a circuit if it goes clockwise; otherwise leaves it unchanged.

    INPUT:

    - ``circuit`` --  a circuit in the graph of a Voronoi Diagram, given
        by a list of edges

    OUTPUT:

    The same circuit if it goes counterclockwise, and its reverse otherwise

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import orient_circuit
        sage: points = [(-4, 0), (4, 0), (0, 4), (0, -4), (0, 0)]
        sage: V = VoronoiDiagram(points)
        sage: E = Graph()
        sage: for reg  in V.regions().values():
        ....:     if reg.rays() or reg.lines():
        ....:         E  = E.union(reg.vertex_graph())
        sage: E.vertices()
        [A vertex at (-2, -2),
         A vertex at (-2, 2),
         A vertex at (2, -2),
         A vertex at (2, 2)]
        sage: cir = E.eulerian_circuit()
        sage: cir
        [(A vertex at (-2, -2), A vertex at (2, -2), None),
         (A vertex at (2, -2), A vertex at (2, 2), None),
         (A vertex at (2, 2), A vertex at (-2, 2), None),
         (A vertex at (-2, 2), A vertex at (-2, -2), None)]
        sage: orient_circuit(cir)
        [(A vertex at (-2, -2), A vertex at (2, -2), None),
         (A vertex at (2, -2), A vertex at (2, 2), None),
         (A vertex at (2, 2), A vertex at (-2, 2), None),
         (A vertex at (-2, 2), A vertex at (-2, -2), None)]
        sage: cirinv = list(reversed([(c[1],c[0],c[2]) for c in cir]))
        sage: cirinv
        [(A vertex at (-2, -2), A vertex at (-2, 2), None),
         (A vertex at (-2, 2), A vertex at (2, 2), None),
         (A vertex at (2, 2), A vertex at (2, -2), None),
         (A vertex at (2, -2), A vertex at (-2, -2), None)]
        sage: orient_circuit(cirinv)
        [(A vertex at (-2, -2), A vertex at (2, -2), None),
         (A vertex at (2, -2), A vertex at (2, 2), None),
         (A vertex at (2, 2), A vertex at (-2, 2), None),
         (A vertex at (-2, 2), A vertex at (-2, -2), None)]

    """
    prec = 53
    vectors = [v[1].vector()-v[0].vector() for v in circuit]
    while True:
        CIF = ComplexIntervalField(prec)
        totalangle = sum((CIF(*vectors[i])/CIF(*vectors[i-1])).argument() for i in range(len(vectors)))
        if totalangle < 0:
            return list(reversed([(c[1], c[0]) + c[2:] for c in circuit]))
        elif totalangle > 0:
            return circuit
        else:
            prec *= 2


def geometric_basis(G, E, p):
    r"""
    Return a geometric basis, based on a vertex.

    INPUT:

    - ``G`` -- the graph of the bounded regions of a Voronoi Diagram

    - ``E`` -- the subgraph of ``G`` formed by the edges that touch an unbounded
      region

    - ``p`` -- a vertex of ``E``

    OUTPUT: A geometric basis. It is formed by a list of sequences of paths.
    Each path is a list of vertices, that form a closed path in `G`, based at
    `p`, that goes to a region, surrounds it, and comes back by the same path it
    came. The concatenation of all these paths is equivalent to `E`.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import geometric_basis
        sage: points = [(-3,0),(3,0),(0,3),(0,-3)]+ [(0,0),(0,-1),(0,1),(1,0),(-1,0)]
        sage: V = VoronoiDiagram(points)
        sage: G = Graph()
        sage: for reg  in V.regions().values():
        ....:     G = G.union(reg.vertex_graph())
        sage: E = Graph()
        sage: for reg  in V.regions().values():
        ....:     if reg.rays() or reg.lines():
        ....:         E  = E.union(reg.vertex_graph())
        sage: p = E.vertices()[0]
        sage: geometric_basis(G, E, p)
        [[A vertex at (-2, -2),
          A vertex at (2, -2),
          A vertex at (2, 2),
          A vertex at (1/2, 1/2),
          A vertex at (1/2, -1/2),
          A vertex at (2, -2),
          A vertex at (-2, -2)],
         [A vertex at (-2, -2),
          A vertex at (2, -2),
          A vertex at (1/2, -1/2),
          A vertex at (1/2, 1/2),
          A vertex at (-1/2, 1/2),
          A vertex at (-1/2, -1/2),
          A vertex at (1/2, -1/2),
          A vertex at (2, -2),
          A vertex at (-2, -2)],
         [A vertex at (-2, -2),
          A vertex at (2, -2),
          A vertex at (1/2, -1/2),
          A vertex at (-1/2, -1/2),
          A vertex at (-2, -2)],
         [A vertex at (-2, -2),
          A vertex at (-1/2, -1/2),
          A vertex at (-1/2, 1/2),
          A vertex at (1/2, 1/2),
          A vertex at (2, 2),
          A vertex at (-2, 2),
          A vertex at (-1/2, 1/2),
          A vertex at (-1/2, -1/2),
          A vertex at (-2, -2)],
         [A vertex at (-2, -2),
          A vertex at (-1/2, -1/2),
          A vertex at (-1/2, 1/2),
          A vertex at (-2, 2),
          A vertex at (-2, -2)]]

    """
    EC = [v[0] for v in orient_circuit(E.eulerian_circuit())]
    i = EC.index(p)
    EC = EC[i:]+EC[:i+1]   # A counterclockwise eulerian circuit on the boundary, based at p
    if len(G.edges()) == len(E.edges()):
        if E.is_cycle():
            return [EC]
    I = Graph()
    for e in G.edges():
        if not E.has_edge(e):
            I.add_edge(e)   # interior graph
    # treat the case where I is empty
    if not I.vertices():
        for v in E.vertices():
            if len(E.neighbors(v)) > 2:
                I.add_vertex(v)

    for i in range(len(EC)):  # q and r are the points we will cut through

        if EC[i] in I.vertices():
            q = EC[i]
            connecting_path = EC[:i]
            break
        elif EC[-i] in I.vertices():
            q = EC[-i]
            connecting_path = list(reversed(EC[-i:]))
            break
    distancequotients = [(E.distance(q, v)**2/I.distance(q, v), v) for v in E.vertices() if v in I.connected_component_containing_vertex(q) and not v == q]
    r = max(distancequotients)[1]
    cutpath = I.shortest_path(q, r)
    Gcut = copy(G)
    Ecut = copy(E)
    Ecut.delete_vertices([q, r])
    Gcut.delete_vertices(cutpath)
    # I think this cannot happen, but just in case, we check it to raise
    # an error instead of giving a wrong answer
    if Gcut.connected_components_number() != 2:
        raise ValueError("unable to compute a correct path")
    G1, G2 = Gcut.connected_components_subgraphs()

    for v in cutpath:
        neighs = G.neighbors(v)
        for n in neighs:
            if n in G1.vertices()+cutpath:
                G1.add_edge(v, n, None)
            if n in G2.vertices()+cutpath:
                G2.add_edge(v, n, None)

    if EC[EC.index(q)+1] in G2.vertices():
        G1, G2 = G2, G1

    E1, E2 = Ecut.connected_components_subgraphs()
    if EC[EC.index(q)+1] in E2.vertices():
        E1, E2 = E2, E1

    for i in range(len(cutpath)-1):
        E1.add_edge(cutpath[i], cutpath[i+1], None)
        E2.add_edge(cutpath[i], cutpath[i+1], None)

    for v in [q, r]:
        for n in E.neighbors(v):
            if n in E1.vertices():
                E1.add_edge(v, n, None)
            if n in E2.vertices():
                E2.add_edge(v, n, None)

    gb1 = geometric_basis(G1, E1, q)
    gb2 = geometric_basis(G2, E2, q)

    resul = [connecting_path + path + list(reversed(connecting_path)) for path in gb1 + gb2]
    for r in resul:
        i = 0
        while i < len(r)-2:
            if r[i] == r[i+2]:
                r.pop(i)
                r.pop(i)
                if i > 0:
                    i -= 1
            else:
                i += 1
    return resul


def braid_monodromy(f):
    r"""
    Compute the braid monodromy of a projection of the curve defined by a polynomial

    INPUT:

    - ``f`` -- a polynomial with two variables, over a number field with an embedding
      in the complex numbers.

    OUTPUT:

    A list of braids. The braids correspond to paths based in the same point;
    each of this paths is the conjugated of a loop around one of the points
    in the discriminant of the projection of ``f``.

    .. NOTE::

        The projection over the `x` axis is used if there are no vertical asymptotes.
        Otherwise, a linear change of variables is done to fall into the previous case.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import braid_monodromy
        sage: R.<x,y> = QQ[]
        sage: f = (x^2-y^3)*(x+3*y-5)
        sage: braid_monodromy(f)  # optional - sirocco
        [s1*s0*(s1*s2)^2*s0*s2^2*s0^-1*(s2^-1*s1^-1)^2*s0^-1*s1^-1,
         s1*s0*(s1*s2)^2*(s0*s2^-1*s1*s2*s1*s2^-1)^2*(s2^-1*s1^-1)^2*s0^-1*s1^-1,
         s1*s0*(s1*s2)^2*s2*s1^-1*s2^-1*s1^-1*s0^-1*s1^-1,
         s1*s0*s2*s0^-1*s2*s1^-1]

    """
    global roots_interval_cache
    (x, y) = f.parent().gens()
    F = f.base_ring()
    g = f.radical()
    d = g.degree(y)
    while not g.coefficient(y**d) in F:
        g = g.subs({x: x + y})
        d = g.degree(y)
    disc = discrim(g)
    V = corrected_voronoi_diagram(tuple(disc))
    G = Graph()
    for reg in V.regions().values():
        G = G.union(reg.vertex_graph())
    E = Graph()
    for reg in V.regions().values():
        if reg.rays() or reg.lines():
            E = E.union(reg.vertex_graph())
    p = next(E.vertex_iterator())
    geombasis = geometric_basis(G, E, p)
    segs = set([])
    for p in geombasis:
        for s in zip(p[:-1], p[1:]):
            if (s[1], s[0]) not in segs:
                segs.add((s[0], s[1]))
    I = QQbar.gen()
    segs = [(a[0]+I*a[1], b[0]+I*b[1]) for (a, b) in segs]
    vertices = list(set(flatten(segs)))
    tocacheverts = [(g, v) for v in vertices]
    populate_roots_interval_cache(tocacheverts)
    gfac = g.factor()
    try:
        braidscomputed = list(braid_in_segment([(gfac, seg[0], seg[1]) for seg in segs]))
    except ChildProcessError:  # hack to deal with random fails first time
        braidscomputed = list(braid_in_segment([(gfac, seg[0], seg[1]) for seg in segs]))
    segsbraids = dict()
    for braidcomputed in braidscomputed:
        seg = (braidcomputed[0][0][1], braidcomputed[0][0][2])
        beginseg = (QQ(seg[0].real()), QQ(seg[0].imag()))
        endseg = (QQ(seg[1].real()), QQ(seg[1].imag()))
        b = braidcomputed[1]
        segsbraids[(beginseg, endseg)] = b
        segsbraids[(endseg, beginseg)] = b.inverse()
    B = b.parent()
    result = []
    for path in geombasis:
        braidpath = B.one()
        for i in range(len(path)-1):
            x0 = tuple(path[i].vector())
            x1 = tuple(path[i+1].vector())
            braidpath = braidpath * segsbraids[(x0, x1)]
        result.append(braidpath)
    return result


def fundamental_group(f, simplified=True, projective=False):
    r"""
    Return a presentation of the fundamental group of the complement of
    the algebraic set defined by the polynomial ``f``.

    INPUT:

    - ``f`` -- a polynomial in two variables, with coefficients in either
      the rationals or a number field with a fixed embedding in `\QQbar`

    - ``simplified`` -- boolean (default: ``True``); if set to ``True`` the
      presentation will be simplified (see below)

    - ``projective`` -- boolean (default: ``False``); if set to ``True``,
      the fundamental group of the complement of the projective completion
      of the curve will be computed, otherwise, the fundamental group of
      the complement in the affine plane will be computed

    If ``simplified`` is ``False``, a Zariski-VanKampen presentation is returned.

    OUTPUT:

    A presentation of the fundamental group of the complement of the
    curve defined by ``f``.

    EXAMPLES::

        sage: from sage.schemes.curves.zariski_vankampen import fundamental_group # optional - sirocco
        sage: R.<x,y> = QQ[]
        sage: f = x^2 + y^3
        sage: fundamental_group(f) # optional - sirocco
        Finitely presented group < ... >
        sage: fundamental_group(f, simplified=False) # optional - sirocco
        Finitely presented group < ... >

    ::

        sage: from sage.schemes.curves.zariski_vankampen import fundamental_group # optional - sirocco
        sage: R.<x,y> = QQ[]
        sage: f = y^3 + x^3
        sage: fundamental_group(f) # optional - sirocco
        Finitely presented group < ... >

    It is also possible to have coefficients in a number field with a
    fixed embedding in `\QQbar`::

        sage: from sage.schemes.curves.zariski_vankampen import fundamental_group # optional - sirocco
        sage: zeta = QQbar['x']('x^2+x+1').roots(multiplicities=False)[0]
        sage: zeta
        -0.50000000000000000? - 0.866025403784439?*I
        sage: F = NumberField(zeta.minpoly(), 'zeta', embedding=zeta)
        sage: F.inject_variables()
        Defining zeta
        sage: R.<x,y> = F[]
        sage: f = y^3 + x^3 +zeta *x + 1
        sage: fundamental_group(f) # optional - sirocco
        Finitely presented group < x0 |  >
    """
    bm = braid_monodromy(f)
    n = bm[0].parent().strands()
    F = FreeGroup(n)

    @parallel
    def relation(x, b):
        return x * b / x
    relations = list(relation([(x, b) for x in F.gens() for b in bm]))
    R = [r[1] for r in relations]
    if projective:
        R.append(prod(F.gens()))
    G = F / R
    if simplified:
        return G.simplified()
    return G
