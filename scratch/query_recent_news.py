import psycopg
import sys

def main():
    db_url = "postgresql://trader:trading_bot_pass@10.0.0.16:5433/trading_bot"
    print(f"Connecting to database: {db_url}")
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, ticker, publisher, url, source, published_at, length(summary) as summary_len, summary
                    FROM news_articles
                    ORDER BY published_at DESC
                    LIMIT 15;
                """)
                rows = cur.fetchall()
                print(f"Fetched {len(rows)} recent articles:\n")
                for r in rows:
                    aid, ticker, publisher, url, source, pub_at, s_len, summary = r
                    print(f"Ticker: {ticker} | Publisher: {publisher} | Source: {source} | Published At: {pub_at}")
                    print(f"  URL: {url}")
                    print(f"  Summary Length: {s_len} chars")
                    print(f"  Snippet: {summary[:150].strip() if summary else 'None'}...")
                    print("-" * 40)
    except Exception as e:
        print(f"Failed to connect or query: {e}")

if __name__ == "__main__":
    main()
