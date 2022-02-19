"""
usage: python3 report_huahua.py <walletaddress> [--format all|cointracking|koinly|..]

Prints transactions and writes CSV(s) to _reports/HUAHUA*.csv

"""

import json
import logging
import math
import os
import pprint

import huahua.api_lcd
import huahua.processor
from huahua.config_huahua import localconfig
from huahua.progress_huahua import SECONDS_PER_PAGE, ProgressHuahua
from common import report_util
from common.Cache import Cache
from common.Exporter import Exporter
from settings_csv import TICKER_HUAHUA

LIMIT = 50
MAX_TRANSACTIONS = 10000


def main():
    wallet_address, export_format, txid, options = report_util.parse_args(TICKER_HUAHUA)
    _read_options(options)

    if txid:
        exporter = txone(wallet_address, txid)
        exporter.export_print()
    else:
        exporter = txhistory(wallet_address)
        report_util.run_exports(TICKER_HUAHUA, wallet_address, exporter, export_format)


def _read_options(options):
    if not options:
        return
    report_util.read_common_options(localconfig, options)

    logging.info("localconfig: %s", localconfig.__dict__)


def wallet_exists(wallet_address):
    return huahua.api_lcd.account_exists(wallet_address)


def txone(wallet_address, txid):
    elem = huahua.api_lcd.get_tx(txid)

    print("Transaction data:")
    pprint.pprint(elem)

    exporter = Exporter(wallet_address)
    huahua.processor.process_tx(wallet_address, elem, exporter)
    return exporter


def estimate_duration(wallet_address):
    return SECONDS_PER_PAGE * huahua.api_lcd.get_txs_count_pages(wallet_address)


def txhistory(wallet_address, job=None, options=None):
    progress = ProgressHuahua()
    exporter = Exporter(wallet_address)

    if options:
        _read_options(options)
    if job:
        localconfig.job = job
        localconfig.cache = True
    if localconfig.cache:
        localconfig.ibc_addresses = Cache().get_ibc_addresses()
        logging.info("Loaded ibc_addresses from cache ...")

    # Fetch count of transactions to estimate progress more accurately
    count_pages = huahua.api_lcd.get_txs_count_pages(wallet_address)
    progress.set_estimate(count_pages)

    # Fetch transactions
    elems = []
    elems.extend(_fetch_txs(wallet_address, progress, count_pages))
    elems = _remove_duplicates(elems)

    progress.report_message(f"Processing {len(elems)} HUAHUA transactions... ")
    huahua.processor.process_txs(wallet_address, elems, exporter)

    if localconfig.cache:
        # Remove entries where no symbol was found
        localconfig.ibc_addresses = {k: v for k, v in localconfig.ibc_addresses.items() if not v.startswith("ibc/")}
        Cache().set_ibc_addresses(localconfig.ibc_addresses)
    return exporter


def _max_pages():
    max_txs = localconfig.limit if localconfig.limit is not None else MAX_TRANSACTIONS
    max_pages = math.ceil(max_txs / LIMIT)
    logging.info("max_txs: %s, max_pages: %s", max_txs, max_pages)
    return max_pages


def _fetch_txs(wallet_address, progress, num_pages):
    if localconfig.debug:
        debug_file = f"_reports/testhuahua.{wallet_address}.json"
        if os.path.exists(debug_file):
            with open(debug_file, "r") as f:
                return json.load(f)

    out = []
    current_page = 0
    # Two passes: is_sender=True (message.sender events) and is_sender=False (transfer.recipient events)
    for is_sender in (True, False):
        offset = 0
        for _ in range(0, _max_pages()):
            message = f"Fetching page {current_page + 1} of {num_pages}"
            progress.report(current_page, message)
            current_page += 1

            elems, offset, _ = huahua.api_lcd.get_txs(wallet_address, is_sender, offset)

            out.extend(elems)
            if offset is None:
                break

    # Debugging only
    if localconfig.debug:
        with open(debug_file, "w") as f:
            json.dump(out, f, indent=4)
        logging.info("Wrote to %s for debugging", debug_file)
    return out


def _remove_duplicates(elems):
    out = []
    txids = set()

    for elem in elems:
        if elem["txhash"] in txids:
            continue

        out.append(elem)
        txids.add(elem["txhash"])

    out.sort(key=lambda elem: elem["timestamp"], reverse=True)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()