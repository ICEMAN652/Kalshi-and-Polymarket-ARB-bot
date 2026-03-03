import requests
import datetime
import pytz
from get_current_markets import get_current_market_urls

POLYMARKET_API_URL = "https://gamma-api.polymarket.com/events"
CLOB_API_URL = "https://clob.polymarket.com/book"
SYMBOL = "BTCUSDT"

_cached_price_to_beat = {}

def get_clob_price(token_id):
    try:
        response = requests.get(CLOB_API_URL, params={"token_id": token_id})
        response.raise_for_status()
        data = response.json()
        asks = data.get('asks', [])
        best_ask = 0.0
        if asks:
            best_ask = min(float(a['price']) for a in asks)
        return best_ask if best_ask > 0 else 0.0
    except Exception as e:
        return None

def get_kraken_open_price(event_start_time):
    try:
        timestamp = int(event_start_time.timestamp())
        url = "https://api.kraken.com/0/public/OHLC"
        params = {
            "pair": "XBTUSD",
            "interval": 60,
            "since": timestamp - 1
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data.get("error") and len(data["error"]) > 0:
            return None, str(data["error"])

        candles = data["result"].get("XXBTZUSD", [])
        if not candles:
            return None, "No candles found"

        # Find candle matching exact timestamp
        for candle in candles:
            if int(candle[0]) == timestamp:
                open_price = float(candle[1])
                return open_price, None

        return None, "Exact candle not found yet"
    except Exception as e:
        return None, str(e)

def get_polymarket_data(slug):
    try:
        response = requests.get(POLYMARKET_API_URL, params={"slug": slug})
        response.raise_for_status()
        data = response.json()
        if not data:
            return None, None, "Event not found"

        event = data[0]
        markets = event.get("markets", [])
        if not markets:
            return None, None, "Markets not found in event"

        market = markets[0]

        # Get the exact candle start time from the API
        event_start_str = market.get("eventStartTime")
        event_start_time = None
        if event_start_str:
            event_start_time = datetime.datetime.fromisoformat(
                event_start_str.replace("Z", "+00:00")
            )

        clob_token_ids = eval(market.get("clobTokenIds", "[]"))
        outcomes = eval(market.get("outcomes", "[]"))

        if len(clob_token_ids) != 2:
            return None, None, "Unexpected number of tokens"

        prices = {}
        for outcome, token_id in zip(outcomes, clob_token_ids):
            price = get_clob_price(token_id)
            prices[outcome] = price if price is not None else 0.0

        return prices, event_start_time, None
    except Exception as e:
        return None, None, str(e)

def fetch_polymarket_data_struct():
    global _cached_price_to_beat
    try:
        from fetch_current_kalshi import fetch_kalshi_data_struct

        market_info = get_current_market_urls()
        polymarket_url = market_info["polymarket"]
        target_time_utc = market_info["target_time_utc"]
        slug = polymarket_url.split("/")[-1]

        poly_prices, event_start_time, poly_err = get_polymarket_data(slug)
        if poly_err:
            return None, f"Polymarket Error: {poly_err}"

        # Get current price from Kalshi (only working Binance source)
        kalshi_data, _ = fetch_kalshi_data_struct()
        current_price = kalshi_data["current_price"] if kalshi_data else None

        # Try to fetch and cache the open price for this market via Kraken
        cache_key = slug
        if cache_key not in _cached_price_to_beat and event_start_time is not None:
            now = datetime.datetime.now(pytz.utc)
            if event_start_time <= now:
                open_price, err = get_kraken_open_price(event_start_time)
                if open_price is not None:
                    _cached_price_to_beat[cache_key] = open_price
                    print(f"[INFO] Locked price to beat for {slug}: ${open_price:,.2f}")
                else:
                    print(f"[WARN] Could not fetch open price: {err}")
            else:
                print(f"[INFO] Candle hasn't opened yet, target: {event_start_time}")

        price_to_beat = _cached_price_to_beat.get(cache_key)

        return {
            "price_to_beat": price_to_beat,
            "current_price": current_price,
            "prices": poly_prices,
            "slug": slug,
            "target_time_utc": target_time_utc
        }, None

    except Exception as e:
        return None, str(e)

def main():
    data, err = fetch_polymarket_data_struct()
    if err:
        print(f"Error: {err}")
        return

    print(f"Fetching data for: {data['slug']}")
    print(f"Target Time (UTC): {data['target_time_utc']}")
    print("-" * 50)

    if data['price_to_beat'] is None:
        print("PRICE TO BEAT: Error")
    else:
        print(f"PRICE TO BEAT: ${data['price_to_beat']:,.2f}")

    if data['current_price'] is None:
        print("CURRENT PRICE: Error")
    else:
        print(f"CURRENT PRICE: ${data['current_price']:,.2f}")

    up_price = data['prices'].get("Up", 0)
    down_price = data['prices'].get("Down", 0)
    print(f"BUY: UP ${up_price:.3f} & DOWN ${down_price:.3f}")

if __name__ == "__main__":
    main()