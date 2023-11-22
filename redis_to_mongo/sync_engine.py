from datetime import timedelta
import time
from collections import defaultdict

from redis_to_mongo.config_loader import Config
from redis_to_mongo.logger import logger
from redis_to_mongo.syncers import *
from redis_to_mongo.redis_api import RedisHandler

from redis_to_mongo.mongo_api import MongoHandler


class SyncEngine:
    """
    The SyncEngine class is responsible for synchronizing data between Redis and MongoDB.
    It uses the RedisHandler to interact with Redis and the Mongo API to interact with MongoDB.
    """

    def __init__(self, config: Config):
        self.config = config
        self.redis_handler = RedisHandler(config)
        self.mongo_handler = MongoHandler(config)
        self.changes_processed = {"unk": 0}
        self.init_syncers()

    def init_syncers(self):
        key_types = self.redis_handler.get_all_key_types()
        self.syncers: list[SyncTypeInterface] = []
        syncer_classes = [
            SyncJSONs,
            SyncLists,
            SyncSets,
            SyncStreams,
            SyncStrings,
            SyncZSets,
        ]
        for syncer in syncer_classes:
            s = syncer(self.config, self.redis_handler)
            s.init(key_types)
            self.syncers.append(s)
            self.changes_processed[s.TYPE] = 0

    def sync(self):
        key_types = self.redis_handler.get_all_key_types()
        implemented_types = set(syncer.TYPE for syncer in self.syncers)
        for key in list(key_types.keys()):
            if key_types[key] not in implemented_types:
                logger.warning(
                    f"Key {key} has unsupported type {key_types[key]} and will be removed from synchronization. Allowed types: {implemented_types=}."
                )
                del key_types[key]
                self.changes_processed["unk"] += 1
        for syncer in self.syncers:
            syncer.sync(key_types)
            self.changes_processed[syncer.TYPE] = syncer.changes_processed  # type: ignore

    def run(self) -> None:
        try:
            self._run()
        except KeyboardInterrupt:
            logger.info("Graceful shutdown initiated.")
            # Perform any necessary cleanup here
            logger.info("SyncEngine has been stopped.")

    def _run(self) -> None:
        """
        Run the SyncEngine indefinitely, synchronizing data between Redis and MongoDB.
        """
        start_time = time.time()
        logger.info("SyncEngine started at: %s", start_time)
        uptime = 0
        while True:
            print("-" * 60)
            round_start_time = time.time()
            self.sync()
            # Add logic for processing sets and metadata streams if necessary
            round_elapsed_time = time.time() - round_start_time
            logger.info(f"Round took: {round_elapsed_time:.5f} seconds")
            elapsed_time = time.time() - start_time
            uptime += elapsed_time
            logger.info(
                f"SyncEngine has been running for: {timedelta(seconds=int(uptime))}"
            )
            self.print_changes_processed_stats()
            sleep_time = max(
                0, self.config.config["sync_interval_sec"] - round_elapsed_time
            )
            logger.info(
                f"Sleeping for: {sleep_time:.2f}/{self.config.config['sync_interval_sec']} seconds."
            )
            time.sleep(sleep_time)
            start_time = time.time()

    def print_changes_processed_stats(self):
        """
        Print the statistics of changes processed in a formatted table.
        """
        print("Changes synced:")
        sorted_stats = sorted(
            self.changes_processed.items(), key=lambda item: (-item[1], item[0])
        )
        max_key_length = max(len(key) for key in self.changes_processed.keys())
        max_value_length = (
            max(len(str(value)) for value in self.changes_processed.values()) + 6
        )
        header = f"{'Type'.ljust(max_key_length)} | {'Count'.rjust(max_value_length)}"
        total_changes = sum(value for _, value in sorted_stats)
        print(header)
        print("-" * (max_key_length + max_value_length + 3))
        print(
            f"{'Total'.ljust(max_key_length)} | {str(total_changes).rjust(max_value_length-3)}"
        )
        print("-" * (max_key_length + max_value_length + 3))
        for key, value in sorted_stats:
            print(
                f"{key.ljust(max_key_length)} | {str(value).rjust(max_value_length-3)}"
            )
