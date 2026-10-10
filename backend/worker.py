"""Separate worker entry. Real collection is intentionally not implemented in S0."""

import argparse
import sys


def refresh_unavailable() -> int:
    print("S0/W00 尚未实现真实来源刷新；没有访问官网或写入业务数据。W01 将实现采集服务。", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Workhunter v2 独立采集 worker")
    parser.add_argument("--db", help="隔离新库路径；S0 尚不读取或写入此路径")
    parser.parse_args()
    return refresh_unavailable()


if __name__ == "__main__":
    raise SystemExit(main())
