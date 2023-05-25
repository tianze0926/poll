"""
Class CHNCPA
"""

import time
from random import Random
from typing import Callable
import xml.etree.ElementTree as ET

import requests
from typeguard import check_type

from logger import logger
from type import Concert, Config, DurationConfig, DurationConfigFixed, DurationConfigGamma

class CHNCPA:
    """
    Core logic of CHNCPA tickets
    """

    def __init__(self, config: Config) -> None:
        check_type(config, Config)
        self.concerts = config["concerts"]
        self.push_config = config['wx_push']
        self.timeout = config["timeout"]

        duration = config["duration"]
        def setup_sleep(duration: DurationConfig) -> Callable[[], None]:
            if duration["type"] == 'fixed':
                check_type(duration, DurationConfigFixed)
                def gen_seconds():
                    return duration["len"]
            elif duration["type"] == 'gamma':
                check_type(duration, DurationConfigGamma)
                random = Random()
                def gen_seconds():
                    return random.gammavariate(duration["k"], duration["theta"])
            def sleep():
                seconds = gen_seconds()
                logger.debug('sleeping for %f seconds', seconds)
                time.sleep(seconds)
            return sleep
        self.sleep_inner = setup_sleep(duration["inner"])
        self.sleep_outer = setup_sleep(duration["outer"])

    def notify(self, concert: Concert, message: str) -> None:
        """
        Send a push message about the opened concert
        """
        url = 'https://wxpusher.zjiecode.com/api/send/message'
        data = {
            "appToken": self.push_config["app_token"],
            "content": message,
            "summary": message[:100],
            "contentType": 3,
            "topicIds": self.push_config["topic_ids"],
            "uids": self.push_config["uids"],
            "url": '',
            "verifyPay": False
        }
        response = requests.post(url, json=data, timeout=self.timeout)
        response_data = response.json()
        if not response_data["success"]:
            raise RuntimeError(f'notify failed: {response_data["msg"]}')

    def check(self, concert: Concert) -> bool:
        """
        Check if the concert is open.
        Returns True if open.
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'
                ' AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
        }
        url = concert["url"]
        response = requests.get(url, headers=headers, timeout=self.timeout)
        if response.status_code != 200:
            message = f'`{concert["url"]}` `{concert["name"]}` query request failed: {response.status_code} {response.text}'
            self.notify(concert, message)
            raise RuntimeError(message)

        try:
            root = ET.fromstring(response.text)
            items = list(root.iter('item'))
            if len(items) != 0:
                names = '\n- '.join([item.find('title').text for item in items])
                message = f'`{concert["name"]}` is out.\n\nNames:\n\n- {names}\n'
                self.notify(concert, message)
                return True
        except Exception as err:
            message = f'Parse failed: {response.text}'
            self.notify(concert, message)
            raise err
        
        return False

    def loop(self):
        """
        Iterate over the concerts
        """
        opened_concerts: dict[str, bool] = {}
        while True:
            for concert in self.concerts:
                if concert["url"] in opened_concerts:
                    continue
                try:
                    opened = self.check(concert)
                    if opened:
                        opened_concerts[concert["url"]] = True
                        logger.info("%s is open", concert["name"])
                    else:
                        logger.debug('%s not opened', concert["name"])

                except Exception as err:
                    logger.exception(err)
                    break

                self.sleep_inner()

            self.sleep_outer()
