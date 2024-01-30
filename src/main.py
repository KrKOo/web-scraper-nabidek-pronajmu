#!/usr/bin/evn python3
import logging
from datetime import datetime
from time import time

import discord
from discord.ext import tasks
import validators

from config import *
from discord_logger import DiscordLogger
from offers_storage import OffersStorage
from scrapers.rental_offer import RentalOffer
from scrapers_manager import create_scrapers, fetch_latest_offers


def get_current_daytime() -> bool:
    return datetime.now().hour in range(6, 22)


client = discord.Client(intents=discord.Intents.default())
daytime = get_current_daytime()
interval_time = (
    config.refresh_interval_daytime_minutes
    if daytime
    else config.refresh_interval_nighttime_minutes
)

scrapers = create_scrapers(config.dispositions)


@client.event
async def on_ready():
    global channel, storage

    dev_channel = client.get_channel(config.discord.dev_channel)
    channel = client.get_channel(config.discord.offers_channel)
    storage = OffersStorage(config.found_offers_file)

    if not config.debug:
        discord_error_logger = DiscordLogger(client, dev_channel, logging.ERROR)
        logging.getLogger().addHandler(discord_error_logger)
    else:
        logging.info("Discord logger is inactive in debug mode")

    logging.info("Available scrapers: " + ", ".join([s.name for s in scrapers]))

    logging.info("Fetching latest offers every {} minutes".format(interval_time))

    process_latest_offers.start()


@tasks.loop(minutes=interval_time)
async def process_latest_offers():
    logging.info("Fetching offers")

    new_offers: list[RentalOffer] = []
    new_offers_in_price_range: list[RentalOffer] = []
    for offer in fetch_latest_offers(scrapers):
        if not storage.contains(offer):
            new_offers.append(offer)
            if str(offer.price).isnumeric() and int(offer.price) <= config.max_price:
                new_offers_in_price_range.append(offer)

    first_time = storage.first_time
    storage.save_offers(new_offers)

    logging.info(
        "Offers fetched (new: {}, new in price range: {}, max price: {})".format(
            len(new_offers), len(new_offers_in_price_range), config.max_price
        )
    )

    if not first_time:
        for offer in new_offers_in_price_range:
            embed = discord.Embed(
                title=offer.title,
                url=offer.link,
                description=offer.location,
                timestamp=datetime.utcnow(),
                color=offer.scraper.color,
            )

            image_url = offer.image_url if validators.url(offer.image_url) else None

            embed.add_field(name="Cena", value=str(offer.price) + " Kč")
            embed.set_author(name=offer.scraper.name, icon_url=offer.scraper.logo_url)
            embed.set_image(url=image_url)

            await channel.send(embed=embed)
    else:
        logging.info("No previous offers, first fetch is running silently")

    global daytime, interval_time
    if daytime != get_current_daytime():  # Pokud stary daytime neodpovida novemu
        daytime = not daytime  # Zneguj daytime (podle podminky se zmenil)

        interval_time = (
            config.refresh_interval_daytime_minutes
            if daytime
            else config.refresh_interval_nighttime_minutes
        )

        logging.info("Fetching latest offers every {} minutes".format(interval_time))
        process_latest_offers.change_interval(minutes=interval_time)

    await channel.edit(topic="Last update {}".format("<t:{}:R>".format(int(time()))))


if __name__ == "__main__":
    logging.basicConfig(
        level=(logging.DEBUG if config.debug else logging.INFO),
        format="%(asctime)s - [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging.debug("Running in debug mode")

    client.run(config.discord.token, log_level=logging.INFO)
