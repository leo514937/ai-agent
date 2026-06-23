#!/usr/bin/env python3
"""
Minimal Redis-compatible server for development.

Implements just enough Redis commands for hm-dianping Spring Boot app:
  - SET/GET/DEL/EXISTS (cache & lock)
  - SETNX (lock)
  - EXPIRE/TTL
  - GEOADD/GEOSEARCH (shop geo queries)
  - ZADD/ZSCORE (blog likes)
  - INCR (seckill stock)
  - DELETE (cache invalidation)

Usage:
    python scripts/start_fake_redis.py
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

# ── In-memory store ──────────────────────────────────────────

store: dict[bytes, dict] = {}  # key -> {value, expiry}

# Special: geo index: "shop:geo:{typeId}" -> [member -> (x, y)]
geo_index: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)


def _get_key(key: bytes) -> Any | None:
    """Get value for key, respecting expiry. Returns decoded value or None."""
    entry = store.get(key)
    if entry is None:
        return None
    expiry = entry.get("expiry")
    if expiry is not None and time.time() > expiry:
        del store[key]
        return None
    return entry["value"]


def _set_key(key: bytes, value: Any, ttl_sec: int | None = None) -> None:
    store[key] = {"value": value}
    if ttl_sec is not None and ttl_sec > 0:
        store[key]["expiry"] = time.time() + ttl_sec


# ── Redis protocol parser ────────────────────────────────────


async def read_command(reader: asyncio.StreamReader) -> list[bytes] | None:
    """Read a Redis RESP (REdis Serialization Protocol) command."""
    try:
        line = await reader.readline()
    except ConnectionResetError:
        return None
    if not line:
        return None

    line = line.strip()
    if not line:
        return None

    if line[0] != ord("*"):
        return None

    try:
        n_args = int(line[1:])
    except (ValueError, IndexError):
        return None

    args = []
    for _ in range(n_args):
        bulk_len_line = await reader.readline()
        if not bulk_len_line:
            return None
        bulk_len_line = bulk_len_line.strip()
        if bulk_len_line[0] != ord("$"):
            return None
        try:
            bulk_len = int(bulk_len_line[1:])
        except (ValueError, IndexError):
            return None
        bulk_data = await reader.readexactly(bulk_len)
        args.append(bulk_data)
        # consume trailing CRLF
        await reader.readline()
    return args


# ── Command handlers ─────────────────────────────────────────


def cmd_ping(args: list[bytes]) -> bytes:
    return b"+PONG\r\n"


def cmd_set(args: list[bytes]) -> bytes:
    key = args[0]
    value = args[1]
    ttl = None
    # Check for EX/PX option
    for i in range(2, len(args) - 1, 2):
        opt = args[i].upper()
        if opt in (b"EX", b"PX"):
            ttl = int(args[i + 1])
            if opt == b"PX":
                ttl = ttl // 1000  # convert ms to s
            break
    _set_key(key, value, ttl)
    return b"+OK\r\n"


def cmd_get(args: list[bytes]) -> bytes:
    val = _get_key(args[0])
    if val is None:
        return b"$-1\r\n"
    return f"${len(val)}\r\n{val}\r\n".encode()


def cmd_del(args: list[bytes]) -> bytes:
    count = 0
    for key in args:
        if key in store:
            del store[key]
            count += 1
    return f":{count}\r\n".encode()


def cmd_exists(args: list[bytes]) -> bytes:
    count = 0
    for key in args:
        if _get_key(key) is not None:
            count += 1
    return f":{count}\r\n".encode()


def cmd_setnx(args: list[bytes]) -> bytes:
    key = args[0]
    if _get_key(key) is not None:
        return b":0\r\n"
    _set_key(key, args[1])
    return b":1\r\n"


def cmd_expire(args: list[bytes]) -> bytes:
    key = args[0]
    sec = int(args[1])
    entry = store.get(key)
    if entry is None:
        return b":0\r\n"
    entry["expiry"] = time.time() + sec
    return b":1\r\n"


def cmd_ttl(args: list[bytes]) -> bytes:
    entry = store.get(args[0])
    if entry is None:
        return b":-2\r\n"
    expiry = entry.get("expiry")
    if expiry is None:
        return b":-1\r\n"
    remain = int(expiry - time.time())
    return f":{max(0, remain)}\r\n".encode()


def cmd_incr(args: list[bytes]) -> bytes:
    key = args[0]
    val = _get_key(key)
    if val is None:
        _set_key(key, b"1")
        return b":1\r\n"
    try:
        new_val = int(val) + 1
    except (ValueError, TypeError):
        return b"-ERR value is not an integer\r\n"
    _set_key(key, str(new_val).encode())
    return f":{new_val}\r\n".encode()


def cmd_decr(args: list[bytes]) -> bytes:
    key = args[0]
    val = _get_key(key)
    if val is None:
        _set_key(key, b"-1")
        return b":-1\r\n"
    try:
        new_val = int(val) - 1
    except (ValueError, TypeError):
        return b"-ERR value is not an integer\r\n"
    _set_key(key, str(new_val).encode())
    return f":{new_val}\r\n".encode()


def cmd_geoadd(args: list[bytes]) -> bytes:
    key = args[0].decode()
    count = 0
    i = 1
    while i + 2 < len(args):
        longitude = float(args[i])
        latitude = float(args[i + 1])
        member = args[i + 2].decode()
        geo_index[key][member] = (longitude, latitude)
        count += 1
        i += 3
    return f":{count}\r\n".encode()


def cmd_geosearch(args: list[bytes]) -> bytes:
    """Simplify: only support GEOSEARCH key FROMLONLAT x y BYRADIUS radius WITHDISTANCE [LIMIT ...]"""
    key = args[0].decode()
    idx = 1

    # Parse FROMLONLAT or FROMMEMBER
    from_type = args[idx].upper()
    idx += 1
    if from_type == b"FROMLONLAT":
        ref_x = float(args[idx])
        ref_y = float(args[idx + 1])
        idx += 2
    elif from_type == b"FROMMEMBER":
        member = args[idx].decode()
        if member not in geo_index.get(key, {}):
            return b"*0\r\n"
        ref_x, ref_y = geo_index[key][member]
        idx += 1
    else:
        return b"-ERR unsupported GEOSEARCH from type\r\n"

    # Parse BYRADIUS
    if args[idx].upper() != b"BYRADIUS":
        return b"-ERR expecting BYRADIUS\r\n"
    idx += 1
    radius = float(args[idx])
    idx += 1
    unit = args[idx].upper()
    idx += 1

    # Convert radius to meters
    if unit == b"KM":
        radius_m = radius * 1000
    elif unit == b"MI":
        radius_m = radius * 1609.34
    else:
        radius_m = radius  # assume meters

    # Optional WITHDIST
    with_dist = False
    if idx < len(args) and args[idx].upper() == b"WITHDIST":
        with_dist = True
        idx += 1

    # Optional LIMIT
    limit = None
    if idx < len(args) and args[idx].upper() == b"LIMIT":
        limit = int(args[idx + 1])

    def haversine(lon1, lat1, lon2, lat2):
        R = 6371000  # meters
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    results: list[tuple[str, float]] = []
    for member, (mx, my) in geo_index.get(key, {}).items():
        dist = haversine(ref_x, ref_y, mx, my)
        if dist <= radius_m:
            results.append((member, dist))

    # Sort by distance
    results.sort(key=lambda r: r[1])

    if limit is not None:
        results = results[:limit]

    # Build RESP array of arrays
    resp = b"*" + str(len(results)).encode() + b"\r\n"
    for member, dist in results:
        if with_dist:
            resp += b"*2\r\n"
            resp += b"$" + str(len(member)).encode() + b"\r\n" + member.encode() + b"\r\n"
            dist_str = f"{dist:.2f}"
            resp += b"$" + str(len(dist_str)).encode() + b"\r\n" + dist_str.encode() + b"\r\n"
        else:
            resp += b"$" + str(len(member)).encode() + b"\r\n" + member.encode() + b"\r\n"
    return resp


def cmd_zadd(args: list[bytes]) -> bytes:
    key = args[0]
    entry = store.get(key)
    if entry is None:
        store[key] = {"value": {}}
    elif not isinstance(store[key]["value"], dict):
        store[key]["value"] = {}
    # ZADD key [NX|XX] [CH] score member ...
    idx = 1
    while idx < len(args) and args[idx].upper() in (b"NX", b"XX", b"CH", b"INCR"):
        idx += 1
    count = 0
    while idx + 1 < len(args):
        score = float(args[idx])
        member = args[idx + 1]
        store[key]["value"][member] = score
        count += 1
        idx += 2
    return f":{count}\r\n".encode()


def cmd_zscore(args: list[bytes]) -> bytes:
    key = args[0]
    member = args[1]
    entry = store.get(key)
    if entry is None:
        return b"$-1\r\n"
    zset = entry.get("value", {})
    if isinstance(zset, dict) and member in zset:
        score_str = str(zset[member])
        return f"${len(score_str)}\r\n{score_str}\r\n".encode()
    return b"$-1\r\n"


def cmd_zrem(args: list[bytes]) -> bytes:
    key = args[0]
    member = args[1]
    entry = store.get(key)
    if entry is None:
        return b":0\r\n"
    zset = entry.get("value", {})
    if isinstance(zset, dict) and member in zset:
        del zset[member]
        return b":1\r\n"
    return b":0\r\n"


def cmd_keys(args: list[bytes]) -> bytes:
    pattern = args[0].decode() if args else "*"
    # Simplified: only support "*" pattern
    if pattern == "*":
        all_keys = list(store.keys())
        resp = b"*" + str(len(all_keys)).encode() + b"\r\n"
        for k in all_keys:
            resp += b"$" + str(len(k)).encode() + b"\r\n" + k + b"\r\n"
        return resp
    return b"*0\r\n"


def cmd_type(args: list[bytes]) -> bytes:
    key = args[0]
    entry = store.get(key)
    if entry is None:
        return b"+none\r\n"
    val = entry["value"]
    if isinstance(val, dict):
        return b"+zset\r\n"
    if isinstance(val, bytes):
        return b"+string\r\n"
    return b"+string\r\n"


def cmd_info(args: list[bytes]) -> bytes:
    # Return minimal info
    info = "# Server\r\nredis_version:6.0.0\r\n"
    return f"${len(info)}\r\n{info}\r\n".encode()


def cmd_select(args: list[bytes]) -> bytes:
    return b"+OK\r\n"


def cmd_command(args: list[bytes]) -> bytes:
    return b"*0\r\n"


def cmd_client(args: list[bytes]) -> bytes:
    if args and args[0].upper() == b"SETNAME":
        return b"+OK\r\n"
    return b"+OK\r\n"


def cmd_scan(args: list[bytes]) -> bytes:
    cursor = args[0].decode() if args else b"0"
    all_keys = list(store.keys())
    resp = b"*2\r\n"
    resp += b"$1\r\n0\r\n"
    resp += b"*" + str(len(all_keys)).encode() + b"\r\n"
    for k in all_keys:
        resp += b"$" + str(len(k)).encode() + b"\r\n" + k + b"\r\n"
    return resp


# ── Command dispatch table ───────────────────────────────────

COMMANDS: dict[bytes, Callable[[list[bytes]], bytes]] = {
    b"PING": cmd_ping,
    b"SET": cmd_set,
    b"GET": cmd_get,
    b"DEL": cmd_del,
    b"EXISTS": cmd_exists,
    b"SETNX": cmd_setnx,
    b"EXPIRE": cmd_expire,
    b"TTL": cmd_ttl,
    b"INCR": cmd_incr,
    b"DECR": cmd_decr,
    b"GEOADD": cmd_geoadd,
    b"GEOSEARCH": cmd_geosearch,
    b"ZADD": cmd_zadd,
    b"ZSCORE": cmd_zscore,
    b"ZREM": cmd_zrem,
    b"KEYS": cmd_keys,
    b"TYPE": cmd_type,
    b"INFO": cmd_info,
    b"SELECT": cmd_select,
    b"COMMAND": cmd_command,
    b"CLIENT": cmd_client,
    b"SCAN": cmd_scan,
    b"MGET": cmd_get,  # simplified
}

# ── TCP Server ────────────────────────────────────────────────


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    print(f"  [connect] {peer}")
    try:
        while True:
            args = await read_command(reader)
            if args is None:
                break
            cmd_name = args[0].upper() if args else b""
            handler = COMMANDS.get(cmd_name)
            if handler:
                try:
                    response = handler(args[1:])
                    writer.write(response)
                except Exception as e:
                    writer.write(b"-ERR " + str(e).encode() + b"\r\n")
            else:
                writer.write(b"-ERR unknown command '" + cmd_name + b"'\r\n")
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    except asyncio.IncompleteReadError:
        pass
    finally:
        print(f"  [disconnect] {peer}")
        writer.close()


async def preload_shop_geo() -> None:
    """Preload shop data into GEO index from MySQL."""
    print("\n  [preload] Loading shop geo data from MySQL ...")
    try:
        import mysql.connector

        conn = mysql.connector.connect(
            host="localhost", port=3306, database="hmdp",
            user="root", password="123456",
        )
        cursor = conn.cursor()
        cursor.execute("SELECT id, x, y, type_id FROM tb_shop")
        count = 0
        for shop_id, x, y, type_id in cursor:
            geo_key = f"shop:geo:{type_id}"
            geo_index[geo_key][str(shop_id)] = (x, y)
            count += 1
        cursor.close()
        conn.close()
        print(f"  [preload] Loaded {count} shops into GEO index")
    except Exception as e:
        print(f"  [preload] Skipped (MySQL not available): {e}")

    # Also preload seckill stock to Redis
    print("  [preload] Loading seckill stock from MySQL ...")
    try:
        import mysql.connector

        conn = mysql.connector.connect(
            host="localhost", port=3306, database="hmdp",
            user="root", password="123456",
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, s.stock FROM tb_voucher v
            JOIN tb_seckill_voucher s ON v.id = s.voucher_id
            WHERE v.type = 1
        """)
        count = 0
        for vid, stock in cursor:
            stock_key = f"seckill:stock:{vid}".encode()
            _set_key(stock_key, str(stock).encode())
            count += 1
        cursor.close()
        conn.close()
        print(f"  [preload] Loaded {count} seckill stocks")
    except Exception as e:
        print(f"  [preload] Skipped: {e}")


async def main() -> None:
    host = "127.0.0.1"
    port = 6379

    print("=" * 50)
    print("  hm-dianping Fake Redis Server")
    print("=" * 50)
    print(f"  Listening on {host}:{port}")
    print("  Press Ctrl+C to stop")

    # Preload data from MySQL
    await preload_shop_geo()

    print(f"\n  [ready] Accepting connections on {host}:{port}\n")

    server = await asyncio.start_server(handle_client, host, port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  [stop] Server stopped.")
