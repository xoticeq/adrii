import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "songwars.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'standard',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS judges (
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (event_id, user_id),
                FOREIGN KEY (event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_url TEXT NOT NULL,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                scored INTEGER DEFAULT 0,
                FOREIGN KEY (event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL,
                judge_id INTEGER NOT NULL,
                score REAL NOT NULL,
                feedback TEXT,
                scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(submission_id, judge_id),
                FOREIGN KEY (submission_id) REFERENCES submissions(id)
            );

            CREATE TABLE IF NOT EXISTS tournament_brackets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL DEFAULT 1,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER,
                winner_id INTEGER,
                is_bye INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                submissions_channel_id INTEGER,
                bot_updates_channel_id INTEGER,
                host_role_ids TEXT DEFAULT '[]',
                setup_complete INTEGER DEFAULT 0
            );
        """)
        await db.commit()


# ── Event ─────────────────────────────────────────────────────────────────────

async def create_event(guild_id: int, name: str, mode: str = "standard") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO events (guild_id, name, mode) VALUES (?, ?, ?)",
            (guild_id, name, mode)
        )
        await db.commit()
        return cursor.lastrowid


async def get_active_event(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM events WHERE guild_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def close_event(event_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE events SET status = 'closed', ended_at = CURRENT_TIMESTAMP WHERE id = ?",
            (event_id,)
        )
        await db.commit()


async def get_all_events(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM events WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ── Judges ────────────────────────────────────────────────────────────────────

async def set_judges(event_id: int, user_ids: list[int]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM judges WHERE event_id = ?", (event_id,))
        await db.executemany(
            "INSERT INTO judges (event_id, user_id) VALUES (?, ?)",
            [(event_id, uid) for uid in user_ids]
        )
        await db.commit()


async def get_judges(event_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM judges WHERE event_id = ?", (event_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


async def is_judge(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM judges WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None


# ── Submissions ───────────────────────────────────────────────────────────────

async def add_submission(event_id: int, user_id: int, username: str, filename: str, file_url: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO submissions (event_id, user_id, username, filename, file_url) VALUES (?, ?, ?, ?, ?)",
            (event_id, user_id, username, filename, file_url)
        )
        await db.commit()
        return cursor.lastrowid


async def get_submission_by_user(event_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM submissions WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_next_unscored_submission(event_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM submissions WHERE event_id = ? AND scored = 0 ORDER BY submitted_at ASC LIMIT 1",
            (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def mark_submission_scored(submission_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE submissions SET scored = 1 WHERE id = ?", (submission_id,)
        )
        await db.commit()


async def get_all_submissions(event_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM submissions WHERE event_id = ? ORDER BY submitted_at ASC",
            (event_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ── Scores ────────────────────────────────────────────────────────────────────

async def add_score(submission_id: int, judge_id: int, score: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO scores (submission_id, judge_id, score) VALUES (?, ?, ?)",
            (submission_id, judge_id, score)
        )
        await db.commit()


async def get_scores_for_submission(submission_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scores WHERE submission_id = ?", (submission_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def has_judge_scored(submission_id: int, judge_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM scores WHERE submission_id = ? AND judge_id = ?",
            (submission_id, judge_id)
        ) as cursor:
            return await cursor.fetchone() is not None


# ── Leaderboard / stats ───────────────────────────────────────────────────────

async def get_leaderboard(guild_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                s.user_id,
                s.username,
                COUNT(DISTINCT s.id) as total_submissions,
                ROUND(AVG(sc.score), 2) as avg_score,
                MAX(sc.score) as best_score,
                COUNT(DISTINCT CASE WHEN tb.winner_id = s.user_id THEN tb.id END) as wins,
                COUNT(DISTINCT CASE WHEN tb.winner_id IS NOT NULL
                    AND tb.winner_id != s.user_id
                    AND (tb.player1_id = s.user_id OR tb.player2_id = s.user_id)
                    THEN tb.id END) as losses
            FROM submissions s
            JOIN scores sc ON sc.submission_id = s.id
            JOIN events e ON e.id = s.event_id
            LEFT JOIN tournament_brackets tb ON tb.event_id = e.id
                AND (tb.player1_id = s.user_id OR tb.player2_id = s.user_id)
                AND tb.is_bye = 0
            WHERE e.guild_id = ?
            GROUP BY s.user_id
            ORDER BY avg_score DESC
        """, (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_user_stats(guild_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                s.user_id,
                s.username,
                COUNT(DISTINCT s.id) as total_submissions,
                ROUND(AVG(sc.score), 2) as avg_score,
                MAX(sc.score) as best_score,
                MIN(sc.score) as lowest_score,
                COUNT(DISTINCT CASE WHEN tb.winner_id = s.user_id THEN tb.id END) as wins,
                COUNT(DISTINCT CASE WHEN tb.winner_id IS NOT NULL
                    AND tb.winner_id != s.user_id
                    AND (tb.player1_id = s.user_id OR tb.player2_id = s.user_id)
                    THEN tb.id END) as losses
            FROM submissions s
            JOIN scores sc ON sc.submission_id = s.id
            JOIN events e ON e.id = s.event_id
            LEFT JOIN tournament_brackets tb ON tb.event_id = e.id
                AND (tb.player1_id = s.user_id OR tb.player2_id = s.user_id)
                AND tb.is_bye = 0
            WHERE e.guild_id = ? AND s.user_id = ?
            GROUP BY s.user_id
        """, (guild_id, user_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


# ── Tournament ────────────────────────────────────────────────────────────────

async def create_bracket_matches(event_id: int, matches: list[dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """INSERT INTO tournament_brackets
               (event_id, round_number, player1_id, player2_id, is_bye, status)
               VALUES (:event_id, :round_number, :player1_id, :player2_id, :is_bye, :status)""",
            matches
        )
        await db.commit()


async def get_bracket(event_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tournament_brackets WHERE event_id = ? ORDER BY round_number, id",
            (event_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_active_match(event_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tournament_brackets WHERE event_id = ? AND status = 'active' LIMIT 1",
            (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def set_match_winner(match_id: int, winner_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tournament_brackets SET winner_id = ?, status = 'done' WHERE id = ?",
            (winner_id, match_id)
        )
        await db.commit()


async def set_match_active(match_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tournament_brackets SET status = 'active' WHERE id = ?",
            (match_id,)
        )
        await db.commit()


# ── Guild settings ────────────────────────────────────────────────────────────

async def get_guild_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            import json
            data["host_role_ids"] = json.loads(data["host_role_ids"] or "[]")
            return data


async def save_guild_settings(guild_id: int, submissions_channel_id: int, host_role_ids: list[int], bot_updates_channel_id: int = None):
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO guild_settings (guild_id, submissions_channel_id, bot_updates_channel_id, host_role_ids, setup_complete)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET
                submissions_channel_id = excluded.submissions_channel_id,
                bot_updates_channel_id = excluded.bot_updates_channel_id,
                host_role_ids = excluded.host_role_ids,
                setup_complete = 1
        """, (guild_id, submissions_channel_id, bot_updates_channel_id, json.dumps(host_role_ids)))
        await db.commit()