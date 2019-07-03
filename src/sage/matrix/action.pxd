from sage.structure.element cimport Element, Matrix, Vector
from sage.structure.parent cimport Parent
from sage.categories.action cimport Action

cdef class MatrixMulAction(Action):
    cdef Parent _codomain
    cdef bint fix_sparseness

cdef class MatrixMatrixAction(MatrixMulAction):
    pass

cdef class MatrixVectorAction(MatrixMulAction):
    pass

cdef class VectorMatrixAction(MatrixMulAction):
    pass

cdef class MatrixPolymapAction(MatrixMulAction):
    cpdef _call_(self, f, mat)

cdef class PolymapMatrixAction(MatrixMulAction):
    cpdef _call_(self, f, mat)