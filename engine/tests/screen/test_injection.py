"""No user value is ever spliced into SQL text.

`compile.py` builds every screen query. Its f-strings may interpolate only: SQL fragments held
in names ending `_sql`, module constants (UPPER_CASE), integer positions (`.index`), and calls
to helpers that return safe SQL (bound placeholders, allow-listed identifiers, validated
aliases, methods named `*_sql`). Anything else, like `{cond.value}` or `{cond.metric}`, fails.
`sql.py` holds those helpers and is tested directly (test_compile.py). Every `execute()` in the
package takes a literal or a compiled statement.
"""

import ast
from pathlib import Path

import glint.screen

SCREEN_DIR = Path(glint.screen.__file__).parent
EXECUTE_MODULES = ("compile.py", "sql.py", "engine.py")
SAFE_CALLS = frozenset(
    {"c", "p", "b", "ident", "bind", "alias", "_layer", "_projection"}
)  # c/p/b: local aliases


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_safe(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id.endswith("_sql") or expr.id.isupper()
    if isinstance(expr, ast.Attribute):
        return expr.attr.endswith("_sql") or expr.attr.isupper() or expr.attr == "index"
    if isinstance(expr, ast.Call):
        name = _call_name(expr) or ""
        return name in SAFE_CALLS or name.endswith("_sql")
    return False


def _unsafe_interpolations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for part in node.values:
            if isinstance(part, ast.FormattedValue) and not _is_safe(part.value):
                bad.append(f"{path.name}:{node.lineno}: {{{ast.unparse(part.value)}}}")
    return bad


def test_no_user_values_in_sql_text() -> None:
    assert _unsafe_interpolations(SCREEN_DIR / "compile.py") == []


def test_no_string_concatenation_into_execute() -> None:
    """`con.execute` takes a literal, a `*_sql` name or a compiled `.sql`/`.counts_sql`."""
    bad: list[str] = []
    for name in EXECUTE_MODULES:
        tree = ast.parse((SCREEN_DIR / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "execute" and node.args:
                arg = node.args[0]
                literal = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                if not (literal or _is_safe(arg) or (
                    isinstance(arg, ast.Attribute) and arg.attr in {"sql", "counts_sql"}
                )):  # fmt: skip
                    bad.append(f"{name}:{node.lineno}: {ast.unparse(arg)}")
    assert bad == []


def _safe_or_const(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant):
        return True
    if isinstance(expr, ast.IfExp):
        return _safe_or_const(expr.body) and _safe_or_const(expr.orelse)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _safe_or_const(expr.left) and _safe_or_const(expr.right)
    if isinstance(expr, ast.JoinedStr):
        return True  # checked by _unsafe_interpolations
    return _is_safe(expr)


def _stringy(expr: ast.expr) -> bool:
    """Looks like string building (integer and list arithmetic is not SQL)."""
    if isinstance(expr, ast.Constant):
        return isinstance(expr.value, str)
    if isinstance(expr, ast.JoinedStr):
        return True
    if isinstance(expr, ast.Name):
        return expr.id.endswith("_sql")
    if isinstance(expr, ast.Attribute):
        return expr.attr.endswith("_sql")
    if isinstance(expr, ast.Call):
        return _call_name(expr) == "str" or _is_safe(expr)
    if isinstance(expr, ast.IfExp):
        return _stringy(expr.body) or _stringy(expr.orelse)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _stringy(expr.left) or _stringy(expr.right)
    return False


def _unsafe_string_building(path: Path) -> list[str]:
    """`.format()`, `%`-formatting, and `+` concatenation of anything but constants or safe
    SQL fragments."""
    bad: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and _call_name(node) == "format":
            bad.append(f"{path.name}:{node.lineno}: .format()")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            if isinstance(node.left, ast.Constant | ast.JoinedStr):
                bad.append(f"{path.name}:{node.lineno}: % formatting")
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Add)
            and _stringy(node)
            and not (_safe_or_const(node.left) and _safe_or_const(node.right))
        ):
            bad.append(f"{path.name}:{node.lineno}: {ast.unparse(node)}")
    return bad


def test_no_concatenation_or_formatting_of_user_values() -> None:
    assert _unsafe_string_building(SCREEN_DIR / "compile.py") == []


def test_the_concatenation_check_catches_splices(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def f(cond, x_sql):\n"
        "    a = 'x >= ' + str(cond.value)\n"
        "    b = 'y = {}'.format(cond.value)\n"
        "    c = 'z = %s' % cond.value\n"
        "    d = x_sql + ' AND ' + x_sql\n"
        "    return a, b, c, d\n"
    )
    found = _unsafe_string_building(sample)
    assert len(found) == 3
    assert not any(":5:" in f for f in found)


def test_the_check_catches_a_spliced_value(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text('def f(cond, p):\n    return f"x >= {cond.value} AND y = {p(1)}"\n')
    assert _unsafe_interpolations(sample) == ["sample.py:2: {cond.value}"]
