import clingo
import clingo.ast
from collections import namedtuple
from src.utils import utils
from src.utils import printer


#
# DEFINES
#


# predicate names
VOLATILE   = utils.VOLATILE
HOLDS      = utils.HOLDS
HOLDSP     = utils.HOLDSP
PREFERENCE = utils.PREFERENCE
OPTIMIZE   = utils.OPTIMIZE
UNSAT      = utils.UNSAT

# others
MODEL = utils.MODEL
EMPTY = ""
M1    = "m1"
M2    = "m2"
M1_M2 = "m1_m2"
SHOW  = "show"
EDGE  = "edge"
ZERO  = "zero"

#
# CLASSES
#


PredicateInfo = namedtuple('PredicateInfo','name underscores ems arity')


class Helper:

    underscores, m1, m2            = None, None, None
    simple_m1, simple_m2, volatile = None, None, None
    unsat, show, edge              = None, None, None
    zero                           = None

    def __init__(self):
        if self.underscores is not None:
            return
        Helper.underscores = utils.underscores
        term = "{}({})".format(self.underscore(MODEL), self.underscore(M1))
        Helper.m1 = clingo.parse_term(term)
        term = "{}({})".format(self.underscore(MODEL), self.underscore(M2))
        Helper.m2 = clingo.parse_term(term)
        term = "{}".format(self.underscore(M1)) # for holds
        Helper.simple_m1 = clingo.parse_term(term)
        term = "{}".format(self.underscore(M2)) # for holds
        Helper.simple_m2 = clingo.parse_term(term)
        Helper.zero = clingo.parse_term("0")
        Helper.volatile = self.underscore(VOLATILE)
        Helper.unsat = self.underscore(UNSAT)
        Helper.show = self.underscore(SHOW)
        Helper.edge = self.underscore(EDGE)

    #TODO: collect many messages, and output them together
    def raise_exception(self, string):
        printer.Printer().print_error(string)
        raise Exception("parsing failed")

    def underscore(self,x):
        return self.underscores + x

    def get_ems(self, loc, ems):
        if   ems == M1:
            return [clingo.ast.Symbol(loc, self.simple_m1)]
        elif ems == M2:
            return [clingo.ast.Symbol(loc, self.simple_m2)]
        elif ems == M1_M2:
            return [clingo.ast.Symbol(loc, self.m1),
                    clingo.ast.Symbol(loc, self.m2)]
        elif ems == ZERO:
            return [clingo.ast.Symbol(loc, self.zero)]
        else:
            return []

    def get_volatile_atom(self, loc):
        no_sign = clingo.ast.Sign.NoSign
        ems = self.get_ems(loc, M1_M2)
        fun = clingo.ast.Function(loc, self.volatile, ems, False)
        return clingo.ast.Literal(loc, no_sign, clingo.ast.SymbolicAtom(fun))


class Visitor:

    def __init__(self):
        for i in dir(self):
            if i.startswith("visit_"):
                setattr(self, "in_"+i[6:], False)

    def visit_children(self, x, *args, **kwargs):
        for key in x.child_keys:
            setattr(x, key, self.visit(getattr(x, key), *args, **kwargs))
        return x

    def visit(self, x, *args, **kwargs):
        if isinstance(x, clingo.ast.AST):
            attr = "visit_" + str(x.type)
            if hasattr(self, attr):
                setattr(x, "in_"+attr, True)  # added
                tmp = getattr(self, attr)(x, *args, **kwargs)
                setattr(x, "in_"+attr, False) # added
                return tmp
            else:
                return self.visit_children(x, *args, **kwargs)
        elif isinstance(x, list):
            return [self.visit(y, *args, **kwargs) for y in x]
        elif x is None:
            return x
        else:
            raise TypeError("unexpected type")


class TermTransformer: # ABSTRACT CLASS

    def __init__(self):
        self.predicates_info = None
        self.default = None
        self.helper = Helper()

    # TO BE DEFINED BY SUBCLASSES
    def set_predicates_info(self):
        pass

    def __get_predicate_info(self, name, arity):
        predicate_info = self.predicates_info.get((name, arity))
        if predicate_info is not None:
            return predicate_info
        return self.default

    # pre: set_predicates_info() was called before
    def transform_function(self, term):
        # get info, change name, add underscores, and update arguments
        predicate_info = self.__get_predicate_info(term.name,
                                                   len(term.arguments))
        if predicate_info.name:
            term.name = predicate_info.name
        term.name = self.helper.underscore(term.name)
        term.name = "_"*predicate_info.underscores + term.name
        term.arguments += self.helper.get_ems(term.location, predicate_info.ems)

    # pre: set_predicates_info() was called before
    def transform_signature(self, sig):
        # get info, change name, add underscores, and update arity
        predicate_info = self.__get_predicate_info(sig.name, sig.arity)
        if predicate_info.name:
            sig.name = predicate_info.name
        sig.name = self.helper.underscore(sig.name)
        sig.name = "_"*predicate_info.underscores + sig.name
        sig.arity += predicate_info.arity

    # returns a Function reifying term with name
    def reify_term(self, term, name):
        return clingo.ast.Function(term.location, name, [term], False)

    # extends a Function with ems
    def extend_function(self, func, ems):
        func.arguments += self.helper.get_ems(func.location, ems)
