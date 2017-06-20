#script (python)

import clingo
import clingo.ast
from collections import namedtuple
from src.utils import utils
from src.utils import printer
import src.program_parser.transitive as transitive


#
# DEFINES
#

# programs
BASE     = utils.BASE
PPROGRAM = utils.PPROGRAM

# predicate names
VOLATILE   = utils.VOLATILE
HOLDS      = utils.HOLDS
HOLDSP     = utils.HOLDSP
PREFERENCE = utils.PREFERENCE
OPTIMIZE   = utils.OPTIMIZE
UNSAT      = utils.UNSAT

# graph
HOLDS_KEY  = (HOLDS,  1)
HOLDSP_KEY = (HOLDSP, 1)
OPEN_NAME  = "open"
NULL       = 0

# others
MODEL    = utils.MODEL
M1       = "m1"
M2       = "m2"
M1_M2    = "m1_m2"
SHOW     = "show"
EDGE     = "edge"

ERROR_PROJECT = """\
error: syntax error, unexpected #project statement in {} program
  {}\n"""
ERROR_MINIMIZE = """\
error: syntax error, unexpected clingo optimization statement in {} program
  {}\n"""
ERROR_DISJOINT = """\
error: syntax error, unexpected disjoint atom in {} program
  {}\n"""
ERROR_CSPLITERAL = """\
error: syntax error, unexpected csp literal in {} program
  {}\n"""
ERROR_KEYWORD = """\
error: syntax error, special predicate depends on non domain atoms in {} program
  {}/{}\n"""

#
# NAMED TUPLE
#
PredicateInfo = namedtuple('PredicateInfo','name underscores ems arity')


class Helper:

    underscores, m1, m2            = None, None, None
    simple_m1, simple_m2, volatile = None, None, None
    unsat, show, edge              = None, None, None

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


class TermTransformer(): # ABSTRACT CLASS

    def __init__(self):
        self.predicates_info = None
        self.default = None
        self.helper = Helper()

    # TO BE REDEFINED BY SUBCLASSES
    def set_predicates_info(self, open):
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
        # return
        return sig

    # pre: set_predicates_info() was called before
    def transform_term_reify(self, term, name):
        # always adds M1_M2
        args = [term] + self.helper.get_ems(term.location, M1_M2)
        return clingo.ast.Function(term.location, name, args, False)


class PreferenceTermTransformer(TermTransformer):

    def __init__(self, type):
        TermTransformer.__init__(self)
        self.__type = type

    def set_predicates_info(self, open):
        self.predicates_info = dict()
        info = PredicateInfo(None, 1, M1_M2, 2)
        for i in open:
            self.predicates_info[i] = info
        # HOLDS and HOLDS' appear always in open, and should be always overriden
        self.predicates_info[(HOLDS, 1)]  = PredicateInfo(None, 0, M1, 1)
        self.predicates_info[(HOLDSP, 1)] = PredicateInfo(HOLDS, 0, M2, 1)
        info = PredicateInfo(None, 0, None, 0)
        for i in [(OPTIMIZE, 1), (PREFERENCE, 2), (PREFERENCE, 5)]:
            if i in self.predicates_info:
                string = ERROR_KEYWORD.format(self.__type, i[0], i[1])
                Helper().raise_exception(string)
            else:
                self.predicates_info[i] = info
        self.default = PredicateInfo(None, 1, None, 0)


class Graph:

    def __init__(self):
        self.__tc = transitive.TransitiveClosure()
        self.__open = transitive.Info((utils.underscores+OPEN_NAME, 0), None)
        holds  = transitive.Info(HOLDS_KEY,  None)
        holdsp = transitive.Info(HOLDSP_KEY, None)
        self.__tc.add_node(self.__open)
        self.__tc.add_node(holds)
        self.__tc.add_node(holdsp)
        self.__tc.add_edge(self.__open, holds, True)
        self.__tc.add_edge(self.__open, holdsp, True)
        self.__heads, self.__bodies = [], []

    def __str__(self):
        out = str(self.__tc)
        out += "\n" + str(self.__tc.get_next((utils.underscores+OPEN_NAME, 0)))
        return out

    #
    # parsing a rule:
    #   add_atom()* process_rule()
    #

    def add_atom(self, term, in_head, in_body, flag=False):
        if in_head:
            self.__heads.append((term, flag))
        elif in_body:
            self.__bodies.append((term, flag))
        else:
            raise utils.FatalException()

    def __get_info(self, term):
        return transitive.Info((term.name, len(term.arguments)), term)

    def process_rule(self):
        i_heads  = [(self.__get_info(i[0]), i[1]) for i in self.__heads]
        i_bodies = [(self.__get_info(i[0]), i[1]) for i in self.__bodies]
        for i in i_heads:
            self.__tc.add_node(i[0])
            if i[1]:
                self.__tc.add_edge(self.__open, i[0], False) 
        for i in i_bodies:
            self.__tc.add_node(i[0])
        for i in i_heads:
            for j in i_bodies:
                self.__tc.add_edge(j[0], i[0], j[1])
        self.__heads, self.__bodies = [], []

    #
    # after parsing all rules
    #

    def get_open(self):
        for i in self.__tc.get_cycles():
            self.__tc.add_edge(self.__open, i, False)
        return self.__tc.get_next(self.__open.key)

    def map_items(self, function):
        self.__tc.map_items(function)


class BodyList:

    def __init__(self, helper):
        self.__bodies = []
        self.__inside = False
        self.__helper = helper

    def in_(self, body, location):
        self.__inside = True
        self.__bodies.append((body, location, []))

    def out(self):
        self.__inside = False

    def add(self, term):
        if not self.__inside:
            return
        self.__bodies[-1][2].append((term.name, len(term.arguments)))

    def update_volatile(self, open_list):
        for i in self.__bodies:
            # for every predicate in the body
            for j in i[2]:
                # if open: append volatile and break
                if j in open_list:
                    i[0].append(self.__helper.get_volatile_atom(i[1]))
                    break


class PreferenceProgramVisitor(Visitor):

    def __init__(self):
        Visitor.__init__(self)
        self.__type = PPROGRAM
        self.__graph = Graph()
        self.__helper = Helper()
        self.__body_list = BodyList(self.__helper)
        self.__term_transformer = PreferenceTermTransformer(self.__type)
        # tracing position
        self.in_Head, self.in_Body = False, False
        self.in_Literal_ConditionalLiteral = False

    # auxiliary
    def __visit_body_literal_list(self, body, location):
        self.__body_list.in_(body, location)
        self.visit(body)
        self.__body_list.out()

    # after visiting all, finish()
    def finish(self):
        # get open predicates from the graph
        open_list = self.__graph.get_open()
        # set predicates_info in term_transformer
        self.__term_transformer.set_predicates_info(open_list)
        # tranform items stored in the graph
        self.__graph.map_items(self.__term_transformer.transform_function) 
        # update bodies with volatile atom
        self.__body_list.update_volatile(open_list)

    #
    # Statements
    #

    def visit_Rule(self, rule):
        # head
        self.in_Head = True
        # if empty head
        if (str(rule.head.type) == "Literal"
            and str(rule.head.atom.type) == "BooleanConstant"
            and str(rule.head.atom.value == False)):
            # add unsat head
            ems = self.__helper.get_ems(rule.location, M1_M2)
            unsat = self.__helper.unsat
            fun = clingo.ast.Function(rule.location, unsat, ems, False)
            atom = clingo.ast.SymbolicAtom(fun)
            rule.head = clingo.ast.Literal(rule.location,
                                           clingo.ast.Sign.NoSign, atom)
        else:
            self.visit(rule.head)
        self.in_Head = False
        # body
        self.in_Body = True
        self.__visit_body_literal_list(rule.body, rule.location)
        self.__graph.process_rule()
        self.in_Body = False
        # return
        return rule

    def visit_Definition(self, d):
        return d

    def __sig_is_det(self, sig):
        return False

    def visit_ShowSignature(self, sig):
        if self.__sig_is_det(sig):
            return sig
        return self.__term_transformer.transform_signature(sig)

    def __body_is_det(self, body):
        return False

    def visit_ShowTerm(self, show):
        if self.__body_is_det(show.body):
            return show
        reify = self.__term_transformer.transform_term_reify
        show.term = reify(show.term, self.__helper.show)
        self.__visit_body_literal_list(show.body, show.location)
        return show

    def visit_Minimize(self, min):
        string = ERROR_MINIMIZE.format(self.__type, str(min))
        self.__helper.raise_exception(string)

    def visit_Script(self, script):
        return script

    def visit_Program(self, prg):
        if prg.name == BASE: 
            return prg
        assert(prg.name == self.__type)
        id1 = clingo.ast.Id(prg.location, self.__helper.underscore(M1))
        id2 = clingo.ast.Id(prg.location, self.__helper.underscore(M2))
        prg.parameters = [id1, id2]
        return prg

    def visit_External(self, ext):
        self.visit(ext.atom)
        self.__visit_body_literal_list(ext.body, ext.location)
        return ext

    # TODO(EFF):do not translate if *all* edge statements are deterministic
    # TODO: Warn if computing many models
    def visit_Edge(self, edge):
        e = self.edge
        edge.u = self.__term_transformer.transform_term_reify(edge.u, e)
        edge.v = self.__term_transformer.transform_term_reify(edge.v, e)
        self.__visit_body_literal_list(edge.body, edge.location)
        return edge

    # TODO(EFF): do not add if head is deterministic
    # TODO: DO!
    def visit_Heuristic(self,heur):
        heur.atom = self.__term_transformer.visit(heur.atom)
        self.__visit_body_literal_list(heur.body, heur.location)
        return heur

    def visit_ProjectAtom(self,atom):
        string = ERROR_PROJECT.format(self.__type, str(atom))
        self.__helper.raise_exception(string)

    def visit_ProjectSignature(self, sig):
        string = ERROR_PROJECT.format(self.__type, str(sig))
        self.__helper.raise_exception(string)


    #
    # Elements
    #

    def visit_Literal(self, lit):
        if str(lit.atom.type) == "SymbolicAtom" and \
           str(lit.atom.term.type) == "Function":
            flag = False
            if (self.in_Head and self.in_Literal_ConditionalLiteral) or \
               (self.in_Body and (
                lit.sign != clingo.ast.Sign.NoSign          or \
                self.in_Aggregate                           or \
                self.in_TheoryAtom or self.in_BodyAggregate or \
                (self.in_ConditionalLiteral and 
                 not self.in_Literal_ConditionalLiteral))):
                flag = True
            self.__graph.add_atom(lit.atom.term, self.in_Head, self.in_Body, flag)
            self.__body_list.add(lit.atom.term)
        self.visit_children(lit)
        return lit

    # csp literals are not accepted
    def visit_CSPLiteral(self,csp):
        string = ERROR_CSPLITERAL.format(self.__type, str(csp))
        self.__helper.raise_exception(string)

    def visit_ConditionalLiteral(self,c):
        self.in_Literal_ConditionalLiteral = True
        self.visit(c.literal)
        self.in_Literal_ConditionalLiteral = False
        self.visit(c.condition)
        c.condition.append(self.__helper.get_volatile_atom(c.location))
        return c

    def visit_Aggregate(self,a):
        self.visit_children(a)
        return a

    def visit_TheoryAtom(self,th):
        self.visit_children(th)
        for i in th.elements:
            i.condition.append(self.__helper.get_volatile_atom(th.location))
        return th

    def visit_BodyAggregate(self,b):
        self.visit_children(b)
        for i in b.elements:
            i.condition.append(self.__helper.get_volatile_atom(b.location))
        return b

    # disjoint atoms are not accepted
    def visit_Disjoint(self,d):
        string = ERROR_DISJOINT.format(self.__type, str(d))
        self.__helper.raise_exception(string)

    def visit_HeadAggregate(self,h):
        self.visit_children(h)
        return h

    def visit_Disjunction(self,d):
        self.visit_children(d)
        return d

