import requests
import json
import os
from datetime import datetime, date, timedelta, time

class SunManager:
    def __init__(self, config):
        # Defaults to Bengaluru, India!
        self.lat = config.get('LATITUDE', '12.9629')
        self.lon = config.get('LONGITUDE', '77.5775')
        self.cache_file = 'data/sun_data.json'
        self.fallback_sunrise = time(6, 0)
        self.fallback_sunset = time(18, 30)

        self.sun_data = self._load_cache()
        self.update_if_needed()

    def _fetch_sun_data(self):
        """Fetches sun data for the next 7 days from the API."""
        today = date.today()
        api_data = {}
        print(f"SHARP SUN MGR: Fetching new sunrise/sunset data for the next 7 days...")
        for i in range(7):
            current_date = today + timedelta(days=i)
            date_str = current_date.strftime('%Y-%m-%d')
            api_url = f"https://api.sunrisesunset.io/json?lat={self.lat}&lng={self.lon}&date={date_str}"
            try:
                response = requests.get(api_url, timeout=10)
                response.raise_for_status()
                data = response.json()
                if data.get('status') == 'OK':
                    # The API returns times in the local timezone of the coordinates.
                    # We just parse the AM/PM format and convert it to 24-hour format.
                    api_time_format = '%I:%M:%S %p'

                    sunrise_dt = datetime.strptime(data['results']['sunrise'], api_time_format)
                    sunset_dt = datetime.strptime(data['results']['sunset'], api_time_format)

                    api_data[date_str] = {
                        'sunrise': sunrise_dt.strftime('%H:%M'),
                        'sunset': sunset_dt.strftime('%H:%M')
                    }
                    print(f"SHARP SUN MGR: Fetched data for {date_str}: Sunrise {api_data[date_str]['sunrise']}, Sunset {api_data[date_str]['sunset']}")
                else:
                    print(f"SHARP SUN MGR: API request failed for {date_str} with status: {data.get('status')}")
                    return None
            except (requests.RequestException, ValueError) as e:
                print(f"SHARP SUN MGR: Error fetching or parsing data for {date_str}: {e}")
                return None # On any error, abort the fetch
        
        api_data['last_updated'] = datetime.now().isoformat()
        return api_data

    def _save_cache(self, data):
        """Saves the fetched data to a local JSON file."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=4)
            print("SHARP SUN MGR: Successfully saved sun data to cache.")
        except IOError as e:
            print(f"SHARP SUN MGR: Error saving sun data cache: {e}")

    def _load_cache(self):
        """Loads sun data from the local cache file."""
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"SHARP SUN MGR: Error loading sun data cache: {e}")
            return {}

    def update_if_needed(self):
        """Checks if the cached data is stale and updates it."""
        last_updated_str = self.sun_data.get('last_updated')
        if not last_updated_str:
            print("SHARP SUN MGR: No cache found. Fetching initial data.")
            new_data = self._fetch_sun_data()
            if new_data:
                self.sun_data = new_data
                self._save_cache(self.sun_data)
            return

        last_updated = datetime.fromisoformat(last_updated_str)
        if (datetime.now() - last_updated).days >= 1:
            print("SHARP SUN MGR: Cached data is stale. Fetching new data.")
            new_data = self._fetch_sun_data()
            if new_data:
                self.sun_data = new_data
                self._save_cache(self.sun_data)
        else:
            print("SHARP SUN MGR: Sun data cache is up to date.")

    def get_sun_times(self, target_date: date):
        """
        Gets sunrise and sunset for a specific date from cache, with fallback.
        Returns a tuple of (sunrise_time, sunset_time).
        """
        date_str = target_date.strftime('%Y-%m-%d')
        times = self.sun_data.get(date_str)

        if times:
            try:
                sunrise = datetime.strptime(times['sunrise'], '%H:%M').time()
                sunset = datetime.strptime(times['sunset'], '%H:%M').time()
                return sunrise, sunset
            except (ValueError, KeyError):
                pass # Fall through to fallback
        
        # Fallback logic
        print(f"SHARP SUN MGR: No valid data for {date_str}. Using fallback times.")
        return self.fallback_sunrise, self.fallback_sunset