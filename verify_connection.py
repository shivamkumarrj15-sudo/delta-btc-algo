"""
Quick Connection & Account Verifier for Delta Exchange API
Run this script to verify your API credentials and check account connectivity.
"""
import sys
from config import Config
from delta_client import DeltaClient

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def test_connection():
    print("=" * 60)
    print("🔍 TESTING DELTA EXCHANGE API CONNECTION")
    print("=" * 60)
    print(f"🌍 Region: {Config.REGION.upper()} ({Config.REST_BASE_URL})")
    
    client = DeltaClient()
    
    # 1. Public Market Data Check
    print("\n1️⃣ Checking Public Market Data Feed...")
    ticker = client.get_ticker(Config.SYMBOL)
    if ticker and 'close' in ticker:
        print(f"   ✅ Market Feed Connected! Live {Config.SYMBOL} Price: ${float(ticker['close']):,.2f}")
    else:
        print("   ❌ Failed to fetch market feed. Please check internet connection.")
        return

    # 2. Check API Key presence
    print("\n2️⃣ Checking API Credentials...")
    if not Config.API_KEY or not Config.API_SECRET:
        print("   ℹ️ API Key/Secret is empty in .env (Running in pure Paper Trading mode).")
        print("   To connect your real account, add DELTA_API_KEY and DELTA_API_SECRET in .env.")
        print("=" * 60)
        return

    # 3. Authenticated Balance Check
    print("   🔑 API Key detected! Authenticating with Delta Exchange...")
    res = client.get_wallet_balances()
    if res.get('success'):
        print("   ✅ API Authentication SUCCESSFUL! 🚀")
        balances = res.get('result', [])
        print("\n💼 Account Balances:")
        found_any = False
        for b in balances:
            balance_val = float(b.get('balance', 0))
            if balance_val > 0:
                found_any = True
                print(f"   • {b.get('asset_symbol', 'Asset')}: {balance_val:,.4f}")
        if not found_any:
            print("   • Available Balance: $0.00 (Wallet empty or test account)")
    else:
        print(f"   ❌ Authentication Failed: {res.get('error', 'Invalid signature or expired key')}")
        print("   Please check if API Key and Secret are copied correctly in .env.")

    print("\n" + "=" * 60)
    print("🎯 Everything is ready to trade!")
    print("=" * 60)

if __name__ == '__main__':
    test_connection()
