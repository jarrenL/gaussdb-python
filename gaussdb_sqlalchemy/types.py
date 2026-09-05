"""Result adapters shared by GaussDB's psycopg2 and psycopg3 dialects."""
import re

from sqlalchemy import types as sqltypes
from sqlalchemy.dialects.postgresql import BYTEA, JSON, JSONB


class GaussDBJSON(JSON):
    def result_processor(self, dialect, coltype):
        # Both supported DBAPIs deserialize JSON themselves, including scalar
        # strings. Parsing only str values here would corrupt e.g. JSON "123".
        return None


class GaussDBJSONB(JSONB):
    def result_processor(self, dialect, coltype):
        return None


class _BinaryResultMixin:
    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, (bytes, bytearray, memoryview)):
                # A bytes value which looks like ASCII hex is still raw data.
                return bytes(value)
            if isinstance(value, str):
                if value.startswith(("\\x", "0x", "0X")):
                    value = value[2:]
                if not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", value):
                    raise ValueError("GaussDB binary result is not valid hex text")
                return bytes.fromhex(value)
            raise TypeError(f"Unsupported GaussDB binary result type: {type(value).__name__}")
        return process


class GaussDBLargeBinary(_BinaryResultMixin, sqltypes.LargeBinary):
    pass


class GaussDBBYTEA(_BinaryResultMixin, BYTEA):
    pass
