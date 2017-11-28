import sys
import ast
import pdb
import re
from typing import List
from collections import deque
import PLGLOBALS
from common import *
from BaseVisitor import BaseVisitor
from SqlVisitor import SqlVisitor

sys.path.append('./built')
from PlSqlParser import PlSqlParser
from PlSqlParserVisitor import PlSqlParserVisitor

OPERATORS = {
    "=": ast.Eq,
    "!=": ast.NotEq,
    "<>": ast.NotEq,
    ">": ast.Gt,
    ">=": ast.GtE,
    "<": ast.Lt,
    "<=": ast.LtE,
    "+": ast.Add,
    "-": ast.Sub,
    "*": ast.Mult,
    "/": ast.Div
}

TYPE_PLTABLE = "PLTABLE"
PKG_PLHELPER = "PLHELPER"
PKG_PLCURSOR = "PLCURSOR"
PKG_PLGLOBALS = "PLGLOBALS"
VALUE_HELPER = "v"

class ScriptVisitor(BaseVisitor):
# pylint: disable=I0011,C0103

    def __init__(self):
        self.pkgs_in_file = []
        self.pkgs_calls_found = []
        self.vars_in_package = []
        self.vars_declared = []
        self.pkg_name: str = None

    def visitSql_script(self, ctx: PlSqlParser.Sql_scriptContext):
        ret = self.visitChildren(ctx)
        body = full_flat_arr(ret)
        imports = self.create_imports()
        body = imports + body
        return ast.Module(
            body=body
        )

    def visitAnonymous_block(self, ctx: PlSqlParser.Anonymous_blockContext):
        ret = self.visitChildren(ctx)
        flat = full_flat_arr(ret)
        return flat

    def visitCreate_package(self, ctx: PlSqlParser.Create_packageContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        ret = deque(ret)
        name: str = ret.popleft().id
        name = get_spec_classname_by_classname(name)
        body = ret
        if len(body) == 0:
            body.append(ast.Pass())
        return ast.ClassDef(
            name=name,
            body=body,
            decorator_list=[],
            bases=[]
        )

    def visitCreate_package_body(self, ctx: PlSqlParser.Create_package_bodyContext):
        self.pkg_name = name = ctx.package_name()[0].getText().upper()
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        spec_classname = get_spec_classname_by_classname(name)
        body = ret[1:]
        self.pkgs_in_file.append(name)
        return ast.ClassDef(
            name=name,
            body=body,
            decorator_list=[],
            bases=[ast.Name(id=spec_classname)]
        )

    def visitFunction_spec(self, ctx: PlSqlParser.Function_specContext):
        return None

    def visitProcedure_spec(self, ctx: PlSqlParser.Procedure_specContext):
        return None

    def visitFunction_body(self, ctx: PlSqlParser.Function_bodyContext):
        return self.visitProcedure_body(ctx)

    def visitProcedure_body(self, ctx: PlSqlParser.Procedure_bodyContext):
        visitor = ScriptVisitor()
        visitor.pkg_name = self.pkg_name
        visitor.vars_in_package = self.vars_in_package
        ret = visitor.manual_visitProcedure_body(ctx)
        add_no_repeat(self.vars_in_package, ret.name)
        add_no_repeat(self.pkgs_calls_found, visitor.pkgs_calls_found)
        return ret

    def manual_visitProcedure_body(self, ctx: PlSqlParser.Procedure_bodyContext):
        args_names: List[str] = [
            param.parameter_name().getText().upper()
            for param in ctx.parameter()
        ]
        add_no_repeat(self.vars_declared, args_names)
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        ret = deque(ret)
        name = ret.popleft()
        args = []
        while True:
            arg = ret[0]
            if not isinstance(arg, ast.arg):
                break
            args.append(arg)
            ret.popleft()
        body = ret
        args = ast.arguments(
            args=args,
            defaults=[],
            vararg=None,
            kwarg=None
        )
        return ast.FunctionDef(
            name=name.id,
            args=args,
            body=body,
            decorator_list=[ast.Name(id="staticmethod")],
            returns=None
        )

    def visitParameter(self, ctx: PlSqlParser.ParameterContext):
        ret = self.visitChildren(ctx)
        name, *_ = full_flat_arr(ret)
        return ast.arg(
            arg=name,
            annotation=None
        )

    def visitSeq_of_statements(self, ctx: PlSqlParser.Seq_of_statementsContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        return ret

    def visitStatement(self, ctx: PlSqlParser.StatementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        statement = ret.popleft()
        return ast.Expr(value=statement)

    def visitLoop_statement(self, ctx: PlSqlParser.Loop_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        if ctx.label_declaration():
            ret.popleft()
            ret.pop()
        expr = ast.While(
            test=ast.NameConstant(value=True),
            body=[],
            orelse=[]
        )
        if ctx.WHILE():
            expr.test = ret.popleft()
        elif ctx.FOR():
            expr = ret.popleft()
        expr.body = list(ret)
        return expr

    def visitCursor_loop_param(self, ctx: PlSqlParser.Cursor_loop_paramContext):
        target = ctx.index_name().getText().upper()
        # declare the variable for being recognized by the children
        add_no_repeat(self.vars_declared, target)
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        target, lower, upper = ret
        upper = ast.BinOp(
            left=upper,
            op=ast.Add(),
            right=ast.Num(n=1)
        )
        return ast.For(
            target=ast.Name(id=target),
            iter=ast.Call(
                func=ast.Name(id="range"),
                args=[lower, upper],
                keywords=[]
            ),
            body=[],
            orelse=[]
        )

    def visitContinue_statement(self, ctx: PlSqlParser.Continue_statementContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        condition = None if not ctx.condition() else ret[0]
        if not condition:
            return ast.Continue()
        else:
            return ast.If(
                test=condition,
                body=[ast.Continue()],
                orelse=[]
            )

    def visitExit_statement(self, ctx: PlSqlParser.Exit_statementContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        condition = None if not ctx.condition() else ret[0]
        if not condition:
            return ast.Break()
        else:
            return ast.If(
                test=condition,
                body=[ast.Break()],
                orelse=[]
            )

    def visitAssignment_statement(self, ctx: PlSqlParser.Assignment_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        name = ret.popleft()
        value = None if not ret else ret[0]
        if isinstance(name, ast.Call):
            # this is not really a function call, let's find what is
            if isinstance(name.func, ast.Name) \
                and name.func.id == VALUE_HELPER:
                # this is an unnecessary plhelper call
                # ie: v(num) := 1
                # we must remove the helper
                # ie: num := 1
                name = name.args[0]
            else:
                # this is a table pl being filled
                # ie: tbObjects(1) := 1
                name = ast.Subscript(
                    value=name.func,
                    slice=ast.Index(value=name.args[0])
                )
        return ast.Assign(
            targets=[name],
            value=value
        )

    def visitSimple_case_statement(self, ctx: PlSqlParser.Simple_case_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        # ret is something like [expr, ELIF, expr, exprs, ELIF, expr, exprs, ELSE exprs]
        case_item = ret.popleft() # the value to compare
        for i, item in enumerate(ret):
            if isinstance(item, ELIF):
                value = ret[i + 1]
                ret[i + 1] = ast.BinOp(
                    left=case_item,
                    op=ast.Eq(),
                    right=value
                )
        ret.popleft() # delete the first ELIF token
        return self.processIf_children(ret)

    def visitSearched_case_statement(self, ctx: PlSqlParser.Searched_case_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        # ret is something like [ELIF, exprs, ELIF, exprs, ELSE exprs]
        ret.popleft() # delete the first ELIF token
        return self.processIf_children(ret)

    def visitIf_statement(self, ctx: PlSqlParser.If_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        return self.processIf_children(ret)

    def processIf_children(self, children: list):
        ret = children
        test = None
        body = []
        orelse = []
        while ret:
            test = ret.pop()
            if isinstance(test, ELSE):
                orelse = body
                body = []
            elif isinstance(test, ELIF):
                orelse = [ast.If(
                    test=body[0],
                    body=body[1:],
                    orelse=orelse
                )]
                body = []
            else:
                body = [test] + body
        return ast.If(
            test=test,
            body=body[1:],
            orelse=orelse
        )

    def visitElsif_part(self, ctx: PlSqlParser.Elsif_partContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        return [ELIF()] + ret

    def visitElse_part(self, ctx: PlSqlParser.Else_partContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        return [ELSE()] + ret

    def visitSimple_case_when_part(self, ctx:PlSqlParser.Simple_case_when_partContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        return [ELIF()] + ret

    def visitSearched_case_when_part(self, ctx: PlSqlParser.Searched_case_when_partContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        return [ELIF()] + ret

    def visitCase_else_part(self, ctx: PlSqlParser.Case_else_partContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        return [ELSE()] + ret

    def visitFunction_call(self, ctx: PlSqlParser.Function_callContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        ret = deque(ret)
        routine_name = ret.popleft()
        args = ret
        return ast.Call(
            func=routine_name,
            args=args,
            keywords=[]
        )

    def visitRoutine_name(self, ctx: PlSqlParser.Routine_nameContext):
        ret = self.visitChildren(ctx)
        pkg, method = full_flat_arr(ret)
        pkg = self.wrap_local_variable(pkg.id)
        return ast.Attribute(
            value=pkg,
            attr=method
        )

    def visitSeq_of_declare_specs(self, ctx: PlSqlParser.Seq_of_declare_specsContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        self.vars_declared = [
            # ast.Assign has targets, ast.AnnAssign has target :/
            isinstance(assign, ast.Assign) and assign.targets[0].id or assign.target.id
            for assign in ret
        ]
        return ret

    def visitCursor_declaration(self, ctx: PlSqlParser.Cursor_declarationContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        name: ast.Name = ret.popleft()
        sql: SQL = ret.popleft()
        add_no_repeat(self.vars_in_package, name.id) # FIXME: not always. only in package_spec
        add_no_repeat(self.pkgs_calls_found, PKG_PLCURSOR)
        return ast.Assign(
            targets=[name],
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=PKG_PLCURSOR),
                    attr="CURSOR"
                ),
                args=[ast.Str(sql.sql)],
                keywords=[]
            )
        )

    def visitSelect_statement(self, ctx: PlSqlParser.Select_statementContext):
        visitor = SqlVisitor()
        visitor.vars_declared = self.vars_declared
        return visitor.visitSelect_statement(ctx)

    def visitOpen_statement(self, ctx: PlSqlParser.Open_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        cursor_name = ret.popleft()
        return ast.Call(
            func=ast.Attribute(
                value=cursor_name,
                attr="OPEN"
            ),
            args=[],
            keywords=[]
        )

    def visitFetch_statement(self, ctx: PlSqlParser.Fetch_statementContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        cursor = ret.popleft()
        destination = ret.popleft()
        return ast.Assign(
            targets=[ast.List(
                elts=[destination]
            )],
            value=ast.Call(
                func=ast.Attribute(
                    value=cursor,
                    attr="FETCH"
                ),
                args=[],
                keywords=[]
            )
        )

    def visitClose_statement(self, ctx: PlSqlParser.Close_statementContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        cursor = ret[0]
        return ast.Call(
            func=ast.Attribute(
                value=cursor,
                attr="CLOSE"
            ),
            args=[],
            keywords=[]
        )

    def visitVariable_declaration(self, ctx: PlSqlParser.Variable_declarationContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        ret = deque(ret)
        name: ast.Name = ret.popleft()
        the_type: TYPE = None
        value = ast.NameConstant(value=None)
        add_no_repeat(self.vars_in_package, name.id)
        if ret and isinstance(ret[0], TYPE):
            the_type = ret.popleft()
            the_type = ast.Name(id=the_type.name)
            value = ast.Call(
                func=the_type,
                args=[],
                keywords=[]
            )
        if ret:
            value = ret.popleft()
        if the_type:
            return ast.AnnAssign(
                target=name,
                annotation=the_type,
                value=value,
                simple=1
            )
        return ast.Assign(
            targets=[name],
            value=value
        )

    def visitReturn_statement(self, ctx: PlSqlParser.Return_statementContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        value = None if not ret else ret[0]
        return ast.Return(value=value)

    def visitConcatenation(self, ctx: PlSqlParser.ConcatenationContext):
        ret = self.visitChildren(ctx)
        operands = full_flat_arr(ret)
        if len(operands) == 2:
            left, right = operands
            operator = OPERATORS[ctx.op.text]()
            return ast.BinOp(
                left=left,
                op=operator,
                right=right
            )
        elif len(operands) == 1:
            return operands
        return ret

    def visitRelational_expression(self, ctx: PlSqlParser.Relational_expressionContext):
        ret = self.visitChildren(ctx)
        expr = flat_arr(ret)
        if len(expr) == 3:
            left, operator, right = expr
            return ast.Compare(
                left=left,
                ops=[operator],
                comparators=[right]
            )
        return expr[0]

    def visitLogical_expression(self, ctx: PlSqlParser.Logical_expressionContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        if ctx.NOT():
            return ast.UnaryOp(
                op=ast.Not(),
                operand=ret[0]
            )
        if len(ret) == 1:
            return ret
        operator = ast.And() if ctx.AND() else ast.Or()
        return ast.BoolOp(
            op=operator,
            values=ret
        )

    def visitType_declaration(self, ctx: PlSqlParser.Type_declarationContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        type_name = ret[0]
        if ctx.table_type_def():
            add_no_repeat(self.vars_in_package, type_name)
            add_no_repeat(self.pkgs_calls_found, TYPE_PLTABLE)
            return ast.Assign(
                targets=ret,
                value=ast.Name(id=TYPE_PLTABLE)
            )
        print("unsupported")
        print(ret)
        return None

    def visitType_spec(self, ctx: PlSqlParser.Type_specContext):
        if ctx.type_name():
            type_name = ctx.type_name().getText().upper()
            return TYPE(type_name)
        self.visitChildren(ctx)
        return None

    def visitRelational_operator(self, ctx: PlSqlParser.Relational_operatorContext):
        text = ctx.getText()
        operator = OPERATORS[text]
        return operator()

    def visitGeneral_element_part(self, ctx: PlSqlParser.General_element_partContext):
        ret = self.visitChildren(ctx)
        ret = deque(full_flat_arr(ret))
        id_expressions = deque(ctx.id_expression())
        ret.popleft() # remove the name from ret, to avoid confusions
        value = id_expressions.popleft().getText().upper()
        value = self.wrap_local_variable(value)
        while id_expressions:
            # ie: a.b.c.d.e.f := 1
            ret.popleft() # remove the names from ret, to avoid confusions
            member = id_expressions.popleft().getText().upper()
            value = ast.Attribute(
                value=value,
                attr=member
            )
        args = None
        if ctx.function_argument():
            args = ctx.function_argument().argument()
            if not args:
                args = []
        if args is not None:
            # ie: some_function(1,2,3)
            args = list(ret) # the remaining values should be the function arguments
            return ast.Call(
                func=value,
                args=args,
                keywords=[]
            )
        # must surround the value in a wrapper
        # we don't know if it is a function call or a value :/
        add_no_repeat(self.pkgs_calls_found, PKG_PLHELPER)
        return ast.Call(
            func=ast.Name(id=VALUE_HELPER),
            args=[value],
            keywords=[]
        )

    def wrap_local_variable(self, value: str):
        if value in self.vars_declared:
            # ie: x := y
            value = ast.Name(id=value)
        elif value != self.pkg_name and value in self.vars_in_package:
            # ie: convert x := 1 en pkgtest.x := 1
            value = ast.Attribute(
                value=ast.Name(id=self.pkg_name),
                attr=value
            )
        elif value in dir(PLGLOBALS.PLGLOBALS):
            add_no_repeat(self.pkgs_calls_found, PKG_PLGLOBALS)
            value = ast.Attribute(
                value=ast.Name(id=PKG_PLGLOBALS),
                attr=value
            )
        else:
            # ie: x := pkg.method()
            add_no_repeat(self.pkgs_calls_found, value)
            value = ast.Name(id=value)
        return value

    def visitRegular_id(self, ctx: PlSqlParser.Regular_idContext):
        if not ctx.REGULAR_ID():
            the_id = ctx.getText().upper()
        else:
            the_id = ctx.REGULAR_ID().getText().upper()
        return ast.Name(id=the_id)

    def visitUnary_expression(self, ctx: PlSqlParser.Unary_expressionContext):
        ret = self.visitChildren(ctx)
        ret = full_flat_arr(ret)
        value = ret[0]
        sign = ctx.children[0].getText()
        if sign == "-":
            return ast.UnaryOp(
                op=ast.USub(),
                operand=value
            )
        return ret

    def visitConstant(self, ctx: PlSqlParser.ConstantContext):
        if ctx.TRUE():
            return ast.NameConstant(value=True)
        if ctx.FALSE():
            return ast.NameConstant(value=False)
        return self.visitChildren(ctx)

    def visitNull_statement(self, ctx: PlSqlParser.Null_statementContext):
        return ast.Pass()

    def visitNumeric(self, ctx: PlSqlParser.NumericContext):
        num = int(ctx.getText())
        return ast.Num(n=num)

    def visitQuoted_string(self, ctx: PlSqlParser.Quoted_stringContext):
        str_value = ctx.CHAR_STRING().getText()[1:-1]
        return ast.Str(str_value)