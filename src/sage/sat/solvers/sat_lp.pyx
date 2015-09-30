r"""
Solve SAT problems Integer Linear Programming

The class defined here is a :class:`~sage.sat.solvers.satsolver.SatSolver` that
solves its instance using :class:`MixedIntegerLinearProgram`. Its performances
can be expected to be slower than when using
:class:`~sage.sat.solvers.cryptominisat.cryptominisat.CryptoMiniSat`.
"""
from satsolver cimport SatSolver
from sage.numerical.mip import MixedIntegerLinearProgram, MIPSolverException

class SatLP(SatSolver):
    def __init__(self, solver=None):
        r"""
        Initializes the instance

        INPUT:

        - ``solver`` -- (default: ``None``) Specify a Linear Program (LP)
          solver to be used. If set to ``None``, the default one is used. For
          more information on LP solvers and which default solver is used, see
          the method
          :meth:`solve <sage.numerical.mip.MixedIntegerLinearProgram.solve>`
          of the class
          :class:`MixedIntegerLinearProgram <sage.numerical.mip.MixedIntegerLinearProgram>`.

        EXAMPLE::

            sage: S=SAT(solver="LP"); S
            an ILP-based SAT Solver
        """
        SatSolver.__init__(self)
        self._LP = MixedIntegerLinearProgram()
        self._vars = self._LP.new_variable(binary=True)

    def var(self):
        """
        Return a *new* variable.

        EXAMPLE::

            sage: S=SAT(solver="LP"); S
            an ILP-based SAT Solver
            sage: S.var()
            1
        """
        nvars = n = self._LP.number_of_variables()
        while nvars==self._LP.number_of_variables():
            n += 1
            self._vars[n] # creates the variable if needed
        return n

    def nvars(self):
        """
        Return the number of variables.

        EXAMPLE::

            sage: S=SAT(solver="LP"); S
            an ILP-based SAT Solver
            sage: S.var()
            1
            sage: S.var()
            2
            sage: S.nvars()
            2
        """
        return self._LP.number_of_variables()

    def add_clause(self, lits):
        """
        Add a new clause to set of clauses.

        INPUT:

        - ``lits`` - a tuple of integers != 0

        .. note::

            If any element ``e`` in ``lits`` has ``abs(e)`` greater
            than the number of variables generated so far, then new
            variables are created automatically.

        EXAMPLE::

            sage: S=SAT(solver="LP"); S
            an ILP-based SAT Solver
            sage: for u,v in graphs.CycleGraph(6).edges(labels=False):
            ....:     u,v = u+1,v+1
            ....:     S.add_clause((u,v))
            ....:     S.add_clause((-u,-v))
        """
        if 0 in lits:
            raise ValueError("0 should not appear in the clause: {}".format(lits))
        p = self._LP
        p.add_constraint(p.sum(self._vars[x] if x>0 else 1-self._vars[-x] for x in lits)
                         >=1)

    def __call__(self):
        """
        Solve this instance.

        OUTPUT:

        - If this instance is SAT: A tuple of length ``nvars()+1``
          where the ``i``-th entry holds an assignment for the
          ``i``-th variables (the ``0``-th entry is always ``None``).

        - If this instance is UNSAT: ``False``

        - If the solver was interrupted before deciding satisfiability
          ``None``.

        EXAMPLE::

            sage: def is_bipartite_SAT(G):
            ....:     S=SAT(solver="LP"); S
            ....:     for u,v in G.edges(labels=False):
            ....:         u,v = u+1,v+1
            ....:         S.add_clause((u,v))
            ....:         S.add_clause((-u,-v))
            ....:     return S
            sage: S = is_bipartite_SAT(graphs.CycleGraph(6))
            sage: S() # random
            [None, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
            sage: True in S()
            True
            sage: S = is_bipartite_SAT(graphs.CycleGraph(7))
            sage: S()
            False
        """
        try:
            self._LP.solve()
        except MIPSolverException:
            return False
        except KeyboardInterrupt:
            return None

        b = self._LP.get_values(self._vars)
        n = max(b)
        return [None]+[b.get(i,False) for i in range(1,n+1)]

    def __repr__(self):
        """
        TESTS::

            sage: S=SAT(solver="LP"); S
            an ILP-based SAT Solver
        """
        return "an ILP-based SAT Solver"
