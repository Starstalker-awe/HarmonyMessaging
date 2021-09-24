def _enable_logging(f):
    import logging
    import functools
    @functools.wraps(f)
    def decorator(*args, **kwargs):
        try:
            import flask
        except ModuleNotFoundError:
            return f(*args, **kwargs)
        disabled = logging.getLogger("cs50").disabled
        if flask.current_app:
            logging.getLogger("cs50").disabled = False
        try:
            return f(*args, **kwargs)
        finally:
            logging.getLogger("cs50").disabled = disabled
    return decorator
class SQL(object):
    def __init__(self, url, **kwargs):
        import logging
        import os
        import re
        import sqlalchemy
        import sqlalchemy.orm
        import sqlite3
        matches = re.search(r"^sqlite:///(.+)$", url)
        if matches:
            if not os.path.exists(matches.group(1)):
                raise RuntimeError("does not exist: {}".format(matches.group(1)))
            if not os.path.isfile(matches.group(1)):
                raise RuntimeError("not a file: {}".format(matches.group(1)))
        self._engine = sqlalchemy.create_engine(url, **kwargs).execution_options(autocommit=False)
        self._logger = logging.getLogger("cs50")
        def connect(dbapi_connection, connection_record):
            dbapi_connection.isolation_level = None
            if type(dbapi_connection) is sqlite3.Connection:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        sqlalchemy.event.listen(self._engine, "connect", connect)
        self._autocommit = True
        disabled = self._logger.disabled
        self._logger.disabled = True
        try:
            self.execute("SELECT 1")
        except sqlalchemy.exc.OperationalError as e:
            e = RuntimeError(_parse_exception(e))
            e.__cause__ = None
            raise e
        finally:
            self._logger.disabled = disabled
    def __del__(self):
        self._disconnect()
    def _disconnect(self):
        if hasattr(self, "_session"):
            self._session.remove()
            delattr(self, "_session")
    @_enable_logging
    def execute(self, sql, *args, **kwargs):
        import decimal
        import re
        import sqlalchemy
        import sqlparse
        import termcolor
        import warnings
        statements = sqlparse.parse(sqlparse.format(sql, strip_comments=True).strip())
        if len(statements) > 1:
            raise RuntimeError("too many statements at once")
        elif len(statements) == 0:
            raise RuntimeError("missing statement")
        if len(args) > 0 and len(kwargs) > 0:
            raise RuntimeError("cannot pass both positional and named parameters")
        for token in statements[0]:
            if token.ttype in [sqlparse.tokens.Keyword, sqlparse.tokens.Keyword.DDL, sqlparse.tokens.Keyword.DML]:
                token_value = token.value.upper()
                if token_value in ["BEGIN", "DELETE", "INSERT", "SELECT", "START", "UPDATE"]:
                    command = token_value
                    break
        else:
            command = None
        tokens = list(statements[0].flatten())
        placeholders = {}
        paramstyle = None
        for index, token in enumerate(tokens):
            if token.ttype == sqlparse.tokens.Name.Placeholder:
                _paramstyle, name = _parse_placeholder(token)
                if not paramstyle:
                    paramstyle = _paramstyle
                elif _paramstyle != paramstyle:
                    raise RuntimeError("inconsistent paramstyle")
                placeholders[index] = name
        if not paramstyle:
            if args:
                paramstyle = "qmark"
            elif kwargs:
                paramstyle = "named"
        _placeholders = ", ".join([str(tokens[index]) for index in placeholders])
        _args = ", ".join([str(self._escape(arg)) for arg in args])
        if paramstyle == "qmark":
            if len(placeholders) != len(args):
                if len(placeholders) < len(args):
                    raise RuntimeError("fewer placeholders ({}) than values ({})".format(_placeholders, _args))
                else:
                    raise RuntimeError("more placeholders ({}) than values ({})".format(_placeholders, _args))
            for i, index in enumerate(placeholders.keys()):
                tokens[index] = self._escape(args[i])
        elif paramstyle == "numeric":
            for index, i in placeholders.items():
                if i >= len(args):
                    raise RuntimeError("missing value for placeholder (:{})".format(i + 1, len(args)))
                tokens[index] = self._escape(args[i])
            indices = set(range(len(args))) - set(placeholders.values())
            if indices:
                raise RuntimeError("unused {} ({})".format(
                    "value" if len(indices) == 1 else "values",
                    ", ".join([str(self._escape(args[index])) for index in indices])))
        elif paramstyle == "named":
            for index, name in placeholders.items():
                if name not in kwargs:
                    raise RuntimeError("missing value for placeholder (:{})".format(name))
                tokens[index] = self._escape(kwargs[name])
            keys = kwargs.keys() - placeholders.values()
            if keys:
                raise RuntimeError("unused values ({})".format(", ".join(keys)))
        elif paramstyle == "format":
            if len(placeholders) != len(args):
                if len(placeholders) < len(args):
                    raise RuntimeError("fewer placeholders ({}) than values ({})".format(_placeholders, _args))
                else:
                    raise RuntimeError("more placeholders ({}) than values ({})".format(_placeholders, _args))
            for i, index in enumerate(placeholders.keys()):
                tokens[index] = self._escape(args[i])
        elif paramstyle == "pyformat":
            for index, name in placeholders.items():
                if name not in kwargs:
                    raise RuntimeError("missing value for placeholder (%{}s)".format(name))
                tokens[index] = self._escape(kwargs[name])
            keys = kwargs.keys() - placeholders.values()
            if keys:
                raise RuntimeError("unused {} ({})".format(
                    "value" if len(keys) == 1 else "values",
                    ", ".join(keys)))
        for index, token in enumerate(tokens):
            if token.ttype in [sqlparse.tokens.Literal.String, sqlparse.tokens.Literal.String.Single]:
                token.value = re.sub("(^'|\s+):", r"\1\:", token.value)
            elif token.ttype == sqlparse.tokens.Literal.String.Symbol:
                token.value = re.sub("(^\"|\s+):", r"\1\:", token.value)
        statement = "".join([str(token) for token in tokens])
        try:
            import flask
            assert flask.current_app
            if not hasattr(flask.g, "_sessions"):
                setattr(flask.g, "_sessions", {})
            sessions = getattr(flask.g, "_sessions")
            if self not in sessions:
                sessions[self] = sqlalchemy.orm.scoping.scoped_session(sqlalchemy.orm.sessionmaker(bind=self._engine))
                if _teardown_appcontext not in flask.current_app.teardown_appcontext_funcs:
                    flask.current_app.teardown_appcontext(_teardown_appcontext)
            session = sessions[self]
        except (ModuleNotFoundError, AssertionError):
            if not hasattr(self, "_session"):
                self._session  = sqlalchemy.orm.scoping.scoped_session(sqlalchemy.orm.sessionmaker(bind=self._engine))
            session = self._session
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                _statement = "".join([str(bytes) if token.ttype == sqlparse.tokens.Other else str(token) for token in tokens])
                if command in ["BEGIN", "START"]:
                    self._autocommit = False
                if self._autocommit:
                    session.execute(sqlalchemy.text("BEGIN"))
                result = session.execute(sqlalchemy.text(statement))
                if self._autocommit:
                    session.execute(sqlalchemy.text("COMMIT"))
                if command in ["COMMIT", "ROLLBACK"]:
                    self._autocommit = True
                ret = True
                if command == "SELECT":
                    rows = [dict(row) for row in result.fetchall()]
                    for row in rows:
                        for column in row:
                            if type(row[column]) is decimal.Decimal:
                                row[column] = float(row[column])
                            elif type(row[column]) is memoryview:
                                row[column] = bytes(row[column])
                    ret = rows
                elif command == "INSERT":
                    if self._engine.url.get_backend_name() in ["postgres", "postgresql"]:
                        try:
                            result = session.execute("SELECT LASTVAL()")
                            ret = result.first()[0]
                        except sqlalchemy.exc.OperationalError:
                            ret = None
                    else:
                        ret = result.lastrowid if result.rowcount == 1 else None
                elif command in ["DELETE", "UPDATE"]:
                    ret = result.rowcount
            except sqlalchemy.exc.IntegrityError as e:
                self._logger.debug(termcolor.colored(statement, "yellow"))
                e = ValueError(e.orig)
                e.__cause__ = None
                raise e
            except (sqlalchemy.exc.OperationalError, sqlalchemy.exc.ProgrammingError) as e:
                self._disconnect()
                self._logger.debug(termcolor.colored(statement, "red"))
                e = RuntimeError(e.orig)
                e.__cause__ = None
                raise e
            else:
                self._logger.debug(termcolor.colored(_statement, "green"))
                return ret
    def _escape(self, value):
        import sqlparse
        def __escape(value):
            import datetime
            import sqlalchemy
            if type(value) is bool:
                return sqlparse.sql.Token(
                    sqlparse.tokens.Number,
                    sqlalchemy.types.Boolean().literal_processor(self._engine.dialect)(value))
            elif type(value) is bytes:
                if self._engine.url.get_backend_name() in ["mysql", "sqlite"]:
                    return sqlparse.sql.Token(sqlparse.tokens.Other, f"x'{value.hex()}'")
                elif self._engine.url.get_backend_name() == "postgresql":
                    return sqlparse.sql.Token(sqlparse.tokens.Other, f"'\\x{value.hex()}'")
                else:
                    raise RuntimeError("unsupported value: {}".format(value))
            elif type(value) is datetime.date:
                return sqlparse.sql.Token(
                    sqlparse.tokens.String,
                    sqlalchemy.types.String().literal_processor(self._engine.dialect)(value.strftime("%Y-%m-%d")))
            elif type(value) is datetime.datetime:
                return sqlparse.sql.Token(
                    sqlparse.tokens.String,
                    sqlalchemy.types.String().literal_processor(self._engine.dialect)(value.strftime("%Y-%m-%d %H:%M:%S")))
            elif type(value) is datetime.time:
                return sqlparse.sql.Token(
                    sqlparse.tokens.String,
                    sqlalchemy.types.String().literal_processor(self._engine.dialect)(value.strftime("%H:%M:%S")))
            elif type(value) is float:
                return sqlparse.sql.Token(
                    sqlparse.tokens.Number,
                    sqlalchemy.types.Float().literal_processor(self._engine.dialect)(value))
            elif type(value) is int:
                return sqlparse.sql.Token(
                    sqlparse.tokens.Number,
                    sqlalchemy.types.Integer().literal_processor(self._engine.dialect)(value))
            elif type(value) is str:
                return sqlparse.sql.Token(
                    sqlparse.tokens.String,
                    sqlalchemy.types.String().literal_processor(self._engine.dialect)(value))
            elif value is None:
                return sqlparse.sql.Token(
                    sqlparse.tokens.Keyword,
                    sqlalchemy.types.NullType().literal_processor(self._engine.dialect)(value))
            else:
                raise RuntimeError("unsupported value: {}".format(value))
        if type(value) in [list, tuple]:
            return sqlparse.sql.TokenList(sqlparse.parse(", ".join([str(__escape(v)) for v in value])))
        else:
            return __escape(value)
def _parse_exception(e):
    import re
    matches = re.search(r"^\(_mysql_exceptions\.OperationalError\) \(\d+, \"(.+)\"\)$", str(e))
    if matches:
        return matches.group(1)
    matches = re.search(r"^\(psycopg2\.OperationalError\) (.+)$", str(e))
    if matches:
        return matches.group(1)
    matches = re.search(r"^\(sqlite3\.OperationalError\) (.+)$", str(e))
    if matches:
        return matches.group(1)
    return str(e)
def _parse_placeholder(token):
    import re
    import sqlparse
    if not isinstance(token, sqlparse.sql.Token) or token.ttype != sqlparse.tokens.Name.Placeholder:
        raise TypeError()
    if token.value == "?":
        return "qmark", None
    matches = re.search(r"^:([1-9]\d*)$", token.value)
    if matches:
        return "numeric", int(matches.group(1)) - 1
    matches = re.search(r"^:([a-zA-Z]\w*)$", token.value)
    if matches:
        return "named", matches.group(1)
    if token.value == "%s":
        return "format", None
    matches = re.search(r"%\((\w+)\)s$", token.value)
    if matches:
        return "pyformat", matches.group(1)
    raise RuntimeError("{}: invalid placeholder".format(token.value))
def _teardown_appcontext(exception=None):
    import flask
    for session in flask.g.pop("_sessions", {}).values():
        session.remove()