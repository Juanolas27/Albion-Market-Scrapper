"""Albion Online Photon operation codes for market-related responses."""


class OperationCodes:
    AUCTION_GET_OFFERS = 74
    AUCTION_GET_REQUESTS = 75
    AUCTION_GET_ITEM_AVERAGE_STATS = 88
    AUCTION_BUY_OFFER = 76
    AUCTION_SELL_REQUEST = 77  # not used
    GOLD_MARKET_GET_INFOS = 237


class EventCodes:
    AUCTION_GET_OFFERS_RESPONSE = 74
    AUCTION_GET_REQUESTS_RESPONSE = 75
    MARKET_HISTORIES_RESPONSE = 88


# Parameter keys for market offer responses
class MarketOfferParams:
    OFFER_LIST = 0
    # Sub-keys within each offer
    ID = 0
    UNIT_PRICE = 1
    AMOUNT = 2
    TIER = 3
    IS_FINISHED = 4
    AUCTION_TYPE = 5  # "offer" = sell, "request" = buy
    BUYER_NAME = 6
    SELLER_NAME = 7
    HAS_BUY_ORDER = 8
    ENCHANTMENT_LEVEL = 9
    QUALITY_LEVEL = 10
    ITEM_TYPE_ID = 11  # e.g. "T4_BAG"
    EXPIRES_UTC = 12
    ITEM_GROUP_TYPE_ID = 13


# City location IDs mapping
CITY_IDS = {
    "Bridgewatch": 3005,
    "Fort Sterling": 3002,
    "Lymhurst": 3003,
    "Martlock": 3004,
    "Thetford": 3000,
    "Caerleon": 3008,
    "Black Market": 3013,
    "Brecilien": 4002,
}

CITY_NAMES = {v: k for k, v in CITY_IDS.items()}
