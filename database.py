"""Управление SQLite базой данных."""
import sqlite3
import json
from datetime import datetime, date
from typing import Optional
from contextlib import contextmanager

from models import Product, Marketplace, Click, Post


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        try:
            yield conn.cursor()
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._cursor() as cur:
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    marketplace TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    referral_url TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    price_original REAL DEFAULT 0,
                    price_sale REAL DEFAULT 0,
                    discount_percent INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0,
                    reviews_count INTEGER DEFAULT 0,
                    category TEXT DEFAULT '',
                    brand TEXT DEFAULT '',
                    is_posted INTEGER DEFAULT 0,
                    post_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(marketplace, external_id)
                );

                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER,
                    content TEXT DEFAULT '',
                    product_ids TEXT DEFAULT '[]',
                    posted_at TEXT,
                    is_scheduled INTEGER DEFAULT 0,
                    scheduled_at TEXT
                );

                CREATE TABLE IF NOT EXISTS clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    user_id INTEGER,
                    ref_hash TEXT DEFAULT '',
                    ip_hash TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    clicked_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    clicks INTEGER DEFAULT 0,
                    posts INTEGER DEFAULT 0,
                    products_added INTEGER DEFAULT 0,
                    top_product_id INTEGER,
                    top_marketplace TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_products_marketplace ON products(marketplace);
                CREATE INDEX IF NOT EXISTS idx_products_posted ON products(is_posted);
                CREATE INDEX IF NOT EXISTS idx_products_discount ON products(discount_percent DESC);
                CREATE INDEX IF NOT EXISTS idx_clicks_product ON clicks(product_id);
                CREATE INDEX IF NOT EXISTS idx_clicks_date ON clicks(clicked_at);
            """)

    def insert_product(self, product: Product) -> int:
        with self._cursor() as cur:
            cur.execute("""
                INSERT OR REPLACE INTO products
                (marketplace, external_id, name, url, referral_url, image_url,
                 price_original, price_sale, discount_percent, rating, reviews_count,
                 category, brand, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                product.marketplace.value, product.external_id, product.name,
                product.url, product.referral_url, product.image_url,
                product.price_original, product.price_sale, product.discount_percent,
                product.rating, product.reviews_count, product.category,
                product.brand,
            ))
            return cur.lastrowid

    def insert_products(self, products: list[Product]) -> int:
        count = 0
        for p in products:
            try:
                self.insert_product(p)
                count += 1
            except sqlite3.IntegrityError:
                pass
        return count

    def insert_products_return_ids(self, products: list[Product]) -> list[Optional[int]]:
        """Как insert_products(), но возвращает id вставленных/обновлённых строк
        в том же порядке, что и products — нужно, когда сразу после вставки
        товар должен быть помечен опубликованным (mark_posted), а не заново
        искаться в базе отдельным запросом (например, при постинге по
        произвольному запросу из Telegram — см. scheduler.run_category_post_cycle).
        """
        ids: list[Optional[int]] = []
        for p in products:
            try:
                ids.append(self.insert_product(p))
            except sqlite3.IntegrityError:
                ids.append(None)
        return ids

    def get_unposted_products(self, limit: int = 10, min_discount: int = 0) -> list[Product]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT * FROM products
                WHERE is_posted = 0 AND discount_percent >= ?
                ORDER BY discount_percent DESC, rating DESC, reviews_count DESC
                LIMIT ?
            """, (min_discount, limit))
            rows = cur.fetchall()
        return [self._row_to_product(r) for r in rows]

    def get_products_by_ids(self, ids: list[int]) -> list[Product]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM products WHERE id IN ({placeholders})", ids)
            rows = cur.fetchall()
        return [self._row_to_product(r) for r in rows]

    def mark_posted(self, product_ids: list[int]):
        with self._cursor() as cur:
            placeholders = ",".join("?" * len(ids := product_ids))
            cur.execute(f"""
                UPDATE products SET is_posted = 1, post_count = post_count + 1,
                updated_at = datetime('now') WHERE id IN ({placeholders})
            """, ids)

    def record_click(self, product_id: int, user_id: Optional[int] = None,
                     ref_hash: str = "", ip_hash: str = "", user_agent: str = ""):
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO clicks (product_id, user_id, ref_hash, ip_hash, user_agent)
                VALUES (?, ?, ?, ?, ?)
            """, (product_id, user_id, ref_hash, ip_hash, user_agent))

    def record_post(self, channel_id: str, message_id: Optional[int],
                    content: str, product_ids: list[int]):
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO posts (channel_id, message_id, content, product_ids, posted_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (channel_id, message_id, content, json.dumps(product_ids)))

    def get_daily_stats(self, days: int = 7) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT date(clicked_at) as day, COUNT(*) as clicks
                FROM clicks WHERE clicked_at >= date('now', ?)
                GROUP BY day ORDER BY day
            """, (f"-{days} days",))
            click_stats = {r["day"]: r["clicks"] for r in cur.fetchall()}

            cur.execute("""
                SELECT date(posted_at) as day, COUNT(*) as posts
                FROM posts WHERE posted_at >= date('now', ?)
                GROUP BY day ORDER BY day
            """, (f"-{days} days",))
            post_stats = {r["day"]: r["posts"] for r in cur.fetchall()}

        all_dates = sorted(set(click_stats.keys()) | set(post_stats.keys()))
        return [
            {"date": d, "clicks": click_stats.get(d, 0), "posts": post_stats.get(d, 0)}
            for d in all_dates
        ]

    def get_top_products(self, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT p.*, COUNT(c.id) as total_clicks
                FROM products p LEFT JOIN clicks c ON p.id = c.product_id
                GROUP BY p.id ORDER BY total_clicks DESC LIMIT ?
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def get_marketplace_stats(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT marketplace,
                       COUNT(*) as total_products,
                       SUM(CASE WHEN is_posted = 1 THEN 1 ELSE 0 END) as posted,
                       SUM(CASE WHEN is_posted = 0 THEN 1 ELSE 0 END) as unposted,
                       AVG(discount_percent) as avg_discount
                FROM products GROUP BY marketplace
            """)
            return [dict(r) for r in cur.fetchall()]

    def get_product_count(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM products")
            return cur.fetchone()[0]

    def _row_to_product(self, row) -> Product:
        return Product(
            id=row["id"],
            marketplace=Marketplace(row["marketplace"]),
            external_id=row["external_id"],
            name=row["name"],
            url=row["url"],
            referral_url=row["referral_url"],
            image_url=row["image_url"],
            price_original=row["price_original"],
            price_sale=row["price_sale"],
            discount_percent=row["discount_percent"],
            rating=row["rating"],
            reviews_count=row["reviews_count"],
            category=row["category"],
            brand=row["brand"],
            is_posted=bool(row["is_posted"]),
            post_count=row["post_count"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.utcnow(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.utcnow(),
        )
