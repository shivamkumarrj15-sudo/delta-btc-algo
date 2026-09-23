"""
Delta Exchange API Client Module
Handles public market data (candles, tickers) and authenticated private endpoints (orders, balances).
"""
import time
import hmac
import hashlib
import json
import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from config import Config

class DeltaClient:
    def __init__(self, api_key: str = None, api_secret: str = None, base_url: str = None):
        self.api_key = api_key or Config.API_KEY
        self.api_secret = api_secret or Config.API_SECRET
        self.base_url = (base_url or Config.REST_BASE_URL).rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'DeltaBtcAlgoBot/1.0'
        })
        self._product_cache = {}

    def _generate_signature(self, method: str, path: str, query_string: str = "", body: str = "") -> tuple:
        """Generate Delta Exchange HMAC SHA256 signature."""
        timestamp = str(int(time.time()))
        message = method.upper() + timestamp + path + query_string + body
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def _request(self, method: str, endpoint: str, params: dict = None, data: dict = None, auth: bool = False) -> Dict[str, Any]:
        """Generic API request wrapper with authentication and error handling."""
        url = f"{self.base_url}{endpoint}"
        headers = {}
        body_str = json.dumps(data) if data else ""
        query_str = ""
        
        if params:
            from urllib.parse import urlencode
            query_str = "?" + urlencode(params)
            
        if auth:
            if not self.api_key or not self.api_secret:
                raise ValueError("API Key and Secret are required for private endpoints.")
            timestamp, signature = self._generate_signature(method, endpoint, query_str, body_str)
            headers['api-key'] = self.api_key
            headers['signature'] = signature
            headers['timestamp'] = timestamp

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=body_str if data else None,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Return structured error
            return {"success": False, "error": str(e)}

    # ==========================================
    # PUBLIC MARKET DATA ENDPOINTS
    # ==========================================

    def get_products(self) -> List[Dict[str, Any]]:
        """Fetch all tradable products from Delta Exchange."""
        res = self._request('GET', '/v2/products')
        if res.get('success') and 'result' in res:
            for p in res['result']:
                self._product_cache[p.get('symbol')] = p
            return res['result']
        return []

    def get_product(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get product details by symbol."""
        if not self._product_cache:
            self.get_products()
        return self._product_cache.get(symbol)

    def get_ticker(self, symbol: str = None) -> Optional[Dict[str, Any]]:
        """Get current live ticker / mark price / best bid-ask."""
        symbol = symbol or Config.SYMBOL
        res = self._request('GET', f'/v2/tickers/{symbol}')
        if res.get('success') and 'result' in res:
            return res['result']
        elif 'result' in res:
            return res['result']
        return None

    def get_candles(self, resolution: str, symbol: str = None, limit: int = 100) -> pd.DataFrame:
        """
        Fetch OHLCV candles from Delta Exchange.
        resolutions supported: '1m', '5m', '15m', '1h', '1d'
        Returns pandas DataFrame: ['time', 'open', 'high', 'low', 'close', 'volume']
        """
        symbol = symbol or Config.SYMBOL
        now = int(time.time())
        
        # Calculate seconds per resolution
        res_map = {
            '1m': 60,
            '3m': 180,
            '5m': 300,
            '15m': 900,
            '1h': 3600,
            '4h': 14400,
            '1d': 86400
        }
        res_seconds = res_map.get(resolution, 60)
        start_time = now - (res_seconds * limit)
        
        params = {
            'resolution': resolution,
            'symbol': symbol,
            'start': start_time,
            'end': now
        }
        
        res = self._request('GET', '/v2/history/candles', params=params)
        
        if res.get('success') and 'result' in res and len(res['result']) > 0:
            df = pd.DataFrame(res['result'])
            # Delta returns [time, open, high, low, close, volume]
            expected_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
            if all(col in df.columns for col in expected_cols):
                df = df[expected_cols]
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df = df.sort_values('time').reset_index(drop=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        
        return pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])

    # ==========================================
    # AUTHENTICATED ENDPOINTS (For Live Mode)
    # ==========================================

    def get_wallet_balances(self) -> Dict[str, Any]:
        """Fetch wallet balances for authenticated account."""
        return self._request('GET', '/v2/wallet/balances', auth=True)

    def get_positions(self, product_id: int = None) -> Dict[str, Any]:
        """Get open positions on Delta Exchange."""
        params = {'product_id': product_id} if product_id else None
        return self._request('GET', '/v2/positions', params=params, auth=True)

    def place_order(self, product_id: int, size: float, side: str, order_type: str = 'market_order',
                    limit_price: str = None, stop_price: str = None, leverage: int = 20) -> Dict[str, Any]:
        """
        Place order on Delta Exchange.
        side: 'buy' or 'sell'
        order_type: 'market_order' or 'limit_order' or 'stop_order'
        """
        data = {
            'product_id': product_id,
            'size': size,
            'side': side.lower(),
            'order_type': order_type,
            'leverage': leverage
        }
        if limit_price:
            data['limit_price'] = str(limit_price)
        if stop_price:
            data['stop_price'] = str(stop_price)
            
        return self._request('POST', '/v2/orders', data=data, auth=True)

    def cancel_order(self, product_id: int, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        data = {'product_id': product_id, 'order_id': order_id}
        return self._request('DELETE', '/v2/orders', data=data, auth=True)
